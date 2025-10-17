import os
import logging
import requests
import json
import time
import schedule
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, request, jsonify, render_template_string
import pytz
import random

# Проверка безопасности - добавьте эту функцию
def check_security():
    """Проверяет, что все токены установлены безопасно"""
    required_tokens = ['TELEGRAM_BOT_TOKEN', 'YANDEX_GPT_API_KEY']
    
    for token_name in required_tokens:
        token_value = os.getenv(token_name)
        if not token_value:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не найден токен {token_name}")
            print("💡 Решение: Создайте файл .env с вашими токенами")
            print("📋 Пример содержимого .env файла:")
            print("TELEGRAM_BOT_TOKEN=ваш_токен_бота")
            print("TELEGRAM_CHANNEL=-1003152210862")
            print("TELEGRAM_GROUP=@ppsupershef_chat")
            print("YANDEX_GPT_API_KEY=ваш_yandex_api_ключ")
            print("YANDEX_FOLDER_ID=b1gb6o9sk0ajjfdaoev8")
            print("DEEPSEEK_API_KEY=ваш_deepseek_ключ")
            return False
    
    print("✅ Все токены загружены безопасно!")
    return True

# Запустить проверку при старте
if not check_security():
    exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация - БЕЗОПАСНАЯ ВЕРСИЯ
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '-1003152210862')
    TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')
    YANDEX_GPT_API_KEY = os.getenv('YANDEX_GPT_API_KEY')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    
    # Настройки часовых поясов
    SERVER_TIMEZONE = pytz.timezone('UTC')
    KEMEROVO_TIMEZONE = pytz.timezone('Asia/Novokuznetsk')

class ContentFormatter:
    """Класс для форматирования контента с новым визуальным форматом"""
    
    # Эмоциональные триггеры
    EMOTIONAL_TRIGGERS = {
        'achievement': [
            "🎯 Станьте версией себя, которой восхищаетесь",
            "🎯 Еда - ваш союзник в достижении амбиций", 
            "🎯 Инвестируйте в свое долголетие сегодня",
            "🎯 Каждая тарелка - шаг к лучшей версии себя"
        ],
        'transformation': [
            "🎯 Превратите прием пищи в инструмент роста",
            "🎯 Осознанное питание - конкурентное преимущество",
            "🎯 Ваше тело заслуживает лучшего топлива", 
            "🎯 Долголетие начинается с сегодняшнего ужина"
        ],
        'community': [
            "🎯 Присоединяйтесь к клубу тех, кто выбирает осознанность",
            "🎯 Вы не одиноки на пути к долголетию",
            "🎯 Сообщество единомышленников для вашего роста",
            "🎯 Вместе мы создаем культуру умного питания"
        ]
    }
    
    # Системный промпт для GPT с новым форматом
    SYSTEM_PROMPT = """Ты эксперт по осознанному долголетию и нейропитанию, нутрициолог и Шеф-повар ресторанов Мишлен. Твоя задача - создавать контент, который превращает прием пищи в инструмент для улучшения качества жизни.

🎯 ФИЛОСОФИЯ: 
"Осознанное питание как инвестиция в энергичную, долгую и продуктивную жизнь"

🎯 ТРЕБОВАНИЯ К ФОРМАТУ:
1. Начинай с эмоционального триггера о качестве жизни
2. Добавляй научное обоснование пользы
3. Давай практические рецепты с точными количествами
4. Объясняй механизм действия на организм
5. Заканчивай призывом к осознанному действию

🎯 ОСОБЕННОСТИ РЕЦЕПТОВ:
- Техники шеф-повара Мишлен, адаптированные для дома
- Научно обоснованная польза каждого ингредиента
- Баланс вкуса и функциональности
- Доступные ингредиенты с максимальной пользой

🎯 ТОН:
- Дружеский, но экспертный
- Мотивирующий, но без излишнего энтузиазма  
- Научный, но доступный
- Вдохновляющий на изменения

🎯 ФОРМАТИРОВАНИЕ:
- Используй эмодзи для выделения ключевых моментов
- Продукты выделяй соответствующими эмодзи
- Научные блоки выделяй эмодзи
- Эмоциональные триггеры начинай с 🎯"""
    
    # Визуальный контент
    VISUAL_CONTENT = {
        'infographics': [
            {'emoji': '📊', 'title': '📊 Правило тарелки', 'desc': '🎯 Идеальное распределение продуктов'},
            {'emoji': '📈', 'title': '📈 Баланс БЖУ', 'desc': '🎯 Оптимальное соотношение белков, жиров, углеводов'},
            {'emoji': '⏱️', 'title': '⏱️ Тайминг приемов пищи', 'desc': '🎯 Когда и что лучше есть'},
            {'emoji': '🥗', 'title': '🥗 Сезонные продукты', 'desc': '🎯 Что есть в текущем сезоне'},
            {'emoji': '💧', 'title': '💧 Гидробаланс', 'desc': '🎯 Схема потребления воды'}
        ]
    }
    
    # Реакции для сообщений
    REACTIONS = [
        {"emoji": "😋", "text": "вкусно"},
        {"emoji": "💪", "text": "полезно"},
        {"emoji": "👨‍🍳", "text": "приготовлю"},
        {"emoji": "📝", "text": "запишу себе"},
        {"emoji": "📚", "text": "на рецепты"}
    ]

    @staticmethod
    def get_emotional_trigger():
        """Возвращает случайный эмоциональный триггер"""
        all_triggers = []
        for category in ContentFormatter.EMOTIONAL_TRIGGERS.values():
            all_triggers.extend(category)
        return random.choice(all_triggers)

    @staticmethod
    def format_philosophy_content(title, content, content_type):
        """Форматирует контент с философией осознанного долголетия"""
        trigger = ContentFormatter.get_emotional_trigger()
        
        # Форматируем реакции
        reactions_line = " | ".join([f"{reaction['emoji']} {reaction['text']}" for reaction in ContentFormatter.REACTIONS])
        
        formatted_content = f"""🎪 КЛУБ ОСОЗНАННОГО ДОЛГОЛЕТИЯ ЧЕРЕЗ ПРАВИЛЬНОЕ ПИТАНИЕ

{trigger}

{title}

{content}

---
💫 Вы не просто читаете рецепт - вы инвестируете в свое долголетие и энергию

📢 Подписывайтесь на канал! → @ppsupershef
💬 Обсуждаем в комментариях! → @ppsupershef_chat

{reactions_line}

🔄 Поделитесь с друзьями! → @ppsupershef"""
        
        return formatted_content

class TimeZoneConverter:
    """Класс для конвертации времени между часовыми поясами"""
    
    @staticmethod
    def kemerovo_to_server_time(kemerovo_time_str):
        """Конвертирует время из Кемерово в серверное время с учетом даты"""
        try:
            # Получаем текущее время в Кемерово с правильной датой
            kemerovo_now = datetime.now(Config.KEMEROVO_TIMEZONE)
            
            # Парсим время из строки
            time_obj = datetime.strptime(kemerovo_time_str, '%H:%M').time()
            
            # Создаем полный datetime в Кемерово
            kemerovo_dt = Config.KEMEROVO_TIMEZONE.localize(
                datetime.combine(kemerovo_now.date(), time_obj)
            )
            
            # Конвертируем в серверное время
            server_dt = kemerovo_dt.astimezone(Config.SERVER_TIMEZONE)
            return server_dt.strftime('%H:%M')
            
        except Exception as e:
            logger.error(f"❌ Ошибка конвертации времени {kemerovo_time_str}: {e}")
            return kemerovo_time_str
    
    @staticmethod
    def get_current_times():
        """Возвращает текущее время в обоих часовых поясах"""
        server_now = datetime.now(Config.SERVER_TIMEZONE)
        kemerovo_now = datetime.now(Config.KEMEROVO_TIMEZONE)
        
        return {
            'server_time': server_now.strftime('%H:%M:%S'),
            'kemerovo_time': kemerovo_now.strftime('%H:%M:%S'),
            'server_date': server_now.strftime('%Y-%m-%d'),
            'kemerovo_date': kemerovo_now.strftime('%Y-%m-%d'),
            'server_timezone': str(Config.SERVER_TIMEZONE),
            'kemerovo_timezone': str(Config.KEMEROVO_TIMEZONE)
        }

class TelegramPolls:
    """Класс для работы с опросами в Telegram"""
    
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def create_poll(self, chat_id, question, options, is_anonymous=True, allows_multiple_answers=False):
        """Создание опроса в Telegram"""
        try:
            url = f"{self.base_url}/sendPoll"
            payload = {
                'chat_id': chat_id,
                'question': question,
                'options': options,
                'is_anonymous': is_anonymous,
                'allows_multiple_answers': allows_multiple_answers,
                'type': 'regular'
            }
            
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"✅ Опрос создан: {question}")
                return result['result']
            else:
                logger.error(f"❌ Ошибка создания опроса: {result}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Исключение при создании опроса: {str(e)}")
            return None

class ChannelAnalytics:
    """Класс для сбора и анализа статистики канала"""
    
    def __init__(self, bot_token, channel_id):
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
    def get_member_count(self):
        """Получение количества подписчиков"""
        try:
            url = f"{self.base_url}/getChatMembersCount"
            payload = {
                'chat_id': self.channel_id
            }
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            if result.get('ok'):
                return result['result']
            return 0
        except Exception as e:
            logger.error(f"❌ Ошибка получения количества подписчиков: {e}")
            return 0
    
    def generate_public_report(self):
        """Генерация публичного отчета для канала"""
        member_count = self.get_member_count()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = f"""📊 ЕЖЕДНЕВНЫЙ ОТЧЕТ КАНАЛА @ppsupershef

👥 Подписчиков: {member_count}
📅 Дата: {current_time}
📍 Время Кемерово: {TimeZoneConverter.get_current_times()['kemerovo_time']}

💫 СЕГОДНЯ В КАНАЛЕ:
• 🧠 Нейропитание для ясности ума
• 💪 Энергия для достижений
• 🛡️ Стратегии долголетия
• 🍰 Умные десерты для здоровья

🎯 ПРИСОЕДИНЯЙТЕСЬ К КЛУБУ ОСОЗНАННОГО ДОЛГОЛЕТИЯ ЧЕРЕЗ ПРАВИЛЬНОЕ ПИТАНИЕ!

#отчет #статистика #клуб"""
        
        return report

# Класс для работы с Telegram каналом
class EliteChannel:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        self.group = Config.TELEGRAM_GROUP
        self.polls_manager = TelegramPolls(self.token)
        self.formatter = ContentFormatter()
        
        # Проверка безопасности токенов
        if not self.token:
            logger.error("❌ Токен бота не установлен. Проверьте переменные окружения.")
            raise ValueError("TELEGRAM_BOT_TOKEN не установлен")
            
        logger.info(f"✅ Инициализирован канал с ID: {self.channel}")
    
    def send_to_telegram(self, message, parse_mode='HTML'):
        """Отправка сообщения в Telegram канал"""
        try:
            if not self.token or not self.channel:
                logger.error("❌ Токен или ID канала не установлены")
                return False
            
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                'chat_id': self.channel,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"✅ Сообщение отправлено в канал {self.channel}")
                return True
            else:
                error_msg = result.get('description', 'Unknown error')
                logger.error(f"❌ Ошибка отправки: {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Исключение при отправке: {str(e)}")
            return False

    def test_connection(self):
        """Тестирование подключения к канала"""
        try:
            if not self.token:
                return {"status": "error", "message": "Токен бота не установлен"}
            
            url = f"https://api.telegram.org/bot{self.token}/getMe"
            response = requests.get(url, timeout=10)
            bot_info = response.json()
            
            if not bot_info.get('ok'):
                return {"status": "error", "message": "Неверный токен бота"}
            
            return {
                "status": "success", 
                "bot": bot_info['result']['username'],
                "channel_id": self.channel
            }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def diagnose_channel(self):
        """Полная диагностика канала и бота"""
        try:
            diagnosis = {
                "status": "running",
                "checks": [],
                "summary": "",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # Проверка 1: Токен бота
            if not self.token:
                diagnosis["checks"].append({"check": "Токен бота", "status": "❌ Ошибка", "details": "Токен не установлен"})
                diagnosis["status"] = "error"
            else:
                diagnosis["checks"].append({"check": "Токен бота", "status": "✅ Успех", "details": "Токен установлен"})
            
            # Проверка 2: Доступность бота
            bot_info = self.test_connection()
            if bot_info["status"] == "success":
                diagnosis["checks"].append({"check": "Доступность бота", "status": "✅ Успех", "details": f"Бот: @{bot_info['bot']}"})
            else:
                diagnosis["checks"].append({"check": "Доступность бота", "status": "❌ Ошибка", "details": bot_info["message"]})
                diagnosis["status"] = "error"
            
            # Проверка 3: ID канала
            if not self.channel:
                diagnosis["checks"].append({"check": "ID канала", "status": "❌ Ошибка", "details": "ID канала не установлен"})
                diagnosis["status"] = "error"
            else:
                diagnosis["checks"].append({"check": "ID канала", "status": "✅ Успех", "details": f"Канал: {self.channel}"})
            
            # Проверка 4: Права бота в канале
            if self.token and self.channel:
                try:
                    url = f"https://api.telegram.org/bot{self.token}/getChat"
                    payload = {'chat_id': self.channel}
                    response = requests.post(url, json=payload, timeout=10)
                    result = response.json()
                    
                    if result.get('ok'):
                        chat_info = result['result']
                        diagnosis["checks"].append({"check": "Права в канале", "status": "✅ Успех", "details": f"Канал: {chat_info.get('title', 'Unknown')}"})
                    else:
                        diagnosis["checks"].append({"check": "Права в канале", "status": "❌ Ошибка", "details": "Бот не имеет доступа к каналу"})
                        diagnosis["status"] = "error"
                except Exception as e:
                    diagnosis["checks"].append({"check": "Права в канале", "status": "⚠️ Предупреждение", "details": f"Не удалось проверить: {str(e)}"})
            
            # Проверка 5: Количество подписчиков
            try:
                analytics = ChannelAnalytics(self.token, self.channel)
                member_count = analytics.get_member_count()
                diagnosis["checks"].append({"check": "Подписчики", "status": "✅ Успех", "details": f"Подписчиков: {member_count}"})
            except Exception as e:
                diagnosis["checks"].append({"check": "Подписчики", "status": "⚠️ Предупреждение", "details": f"Не удалось получить: {str(e)}"})
            
            # Проверка 6: Отправка тестового сообщения
            if diagnosis["status"] != "error":
                test_message = "🔧 Тестовое сообщение диагностики"
                success = self.send_to_telegram(test_message)
                if success:
                    diagnosis["checks"].append({"check": "Отправка сообщений", "status": "✅ Успех", "details": "Тестовое сообщение отправлено"})
                else:
                    diagnosis["checks"].append({"check": "Отправка сообщений", "status": "❌ Ошибка", "details": "Не удалось отправить сообщение"})
                    diagnosis["status"] = "error"
            
            # Сводка
            if diagnosis["status"] == "error":
                diagnosis["summary"] = "❌ Требуется внимание: обнаружены критические ошибки"
            elif diagnosis["status"] == "running":
                diagnosis["summary"] = "✅ Все системы работают нормально"
            else:
                diagnosis["summary"] = "⚠️ Есть предупреждения, но система работает"
            
            return diagnosis
            
        except Exception as e:
            return {
                "status": "error",
                "checks": [{"check": "Общая диагностика", "status": "❌ Ошибка", "details": f"Исключение: {str(e)}"}],
                "summary": "❌ Ошибка диагностики",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    
    def send_poll(self, poll_type='content_preference'):
        """Отправка опроса в канал"""
        try:
            poll_data = {
                'question': "🎯 Какой аспект осознанного питания вам наиболее интересен?",
                'options': ['🧠 Нейропитание', '💪 Энергия', '🛡️ Долголетие', '🍽️ Гастрономия']
            }
            return self.polls_manager.create_poll(self.channel, poll_data['question'], poll_data['options'])
        except Exception as e:
            logger.error(f"❌ Ошибка отправки опроса: {str(e)}")
            return None
    
    def send_visual_content(self, content_type='infographics'):
        """Отправка визуального контента"""
        try:
            visual_item = random.choice(self.formatter.VISUAL_CONTENT[content_type])
            message = f"""🎨 {visual_item['title']}

{visual_item['desc']}

💡 Сохраните эту карточку - пригодится в планировании питания!

📱 Поделитесь с друзьями, которым это может быть полезно

#инфографика #осознанноепитание #долголетие"""
            
            return self.send_to_telegram(message)
        except Exception as e:
            logger.error(f"❌ Ошибка отправки визуального контента: {str(e)}")
            return False

# Генерация контента
class ContentGenerator:
    def __init__(self):
        self.yandex_key = Config.YANDEX_GPT_API_KEY
        self.yandex_folder = Config.YANDEX_FOLDER_ID
        self.formatter = ContentFormatter()
        
        # Проверка безопасности API ключей
        if not self.yandex_key:
            logger.error("❌ Yandex GPT API ключ не установлен. Проверьте переменные окружения.")
            raise ValueError("YANDEX_GPT_API_KEY не установлен")
            
        logger.info("✅ Инициализирован генератор контента")
    
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
                    'maxTokens': 1500
                },
                'messages': [
                    {
                        'role': 'system',
                        'text': ContentFormatter.SYSTEM_PROMPT
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

    # 🧠 НЕЙРОПИТАНИЕ - ПОНЕДЕЛЬНИК
    def generate_neuro_breakfast(self):
        """Генерация нейрозавтрака для ясности ума"""
        prompt = """Создай рецепт завтрака, который запускает когнитивные функции на полную мощность.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Начни день с ясностью ума, которая превратит задачи в достижения"

🔬 НАУЧНЫЕ КОМПОНЕНТЫ:
- 🧠 Омега-3 для нейропластичности
- 🛡️ Антиоксиданты для защиты мозга
- 💡 Холин для памяти и обучения
- 🎯 L-тирозин для фокуса"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА", content, "breakfast")
        
        fallback = """🥑 Омлет с авокадо и шпинатом

🎯 ИНГРЕДИЕНТЫ:
• 🥚 Яйца - 2 шт
• 🥑 Авокадо - ½ шт  
• 🥬 Шпинат - 50 г
• 🌰 Грецкие орехи - 20 г
• 🫒 Оливковое масло - 1 ч.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Взбейте яйца с щепоткой соли
2. Обжарьте шпинат на оливковом масле 2 минуты
3. Влейте яйца, готовьте на среднем огне 5-7 минут
4. Подавайте с ломтиками авокадо и грецкими орехами

💡 НАУЧНОЕ ОБОСНОВАНИЕ: 
🥑 Авокадо содержит омега-9 для мембран нейронов
🥬 Шпинат - лютеин для когнитивных функций  
🌰 Грецкие орехи - омега-3 для нейропластичности"""
        return self.formatter.format_philosophy_content("🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА", fallback, "breakfast")

    def generate_neuro_lunch(self):
        """Генерация нейро-обеда для фокуса и концентрации"""
        prompt = """Создай рецепт обеда, который поддерживает когнитивные функции во второй половине дня.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Обед, который превращает послеобеденный спад в продуктивный прорыв"

🔬 НАУЧНЫЕ КОМПОНЕНТЫ:
- 🧠 Белки для устойчивой энергии
- ⚡ Сложные углеводы для стабильного уровня глюкозы
- 🎯 Омега-3 для нейропластичности
- 🛡️ Антиоксиданты против окислительного стресса"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🎯 НЕЙРО-ОБЕД ДЛЯ ФОКУСА", content, "lunch")
        
        fallback = """🍣 Лосось с киноа и овощами

🎯 ИНГРЕДИЕНТЫ:
• 🐟 Лосось - 150 г
• 🌾 Киноа - 100 г (сухая)
• 🥦 Брокколи - 200 г
• 🥕 Морковь - 1 шт
• 🫒 Оливковое масло - 1 ст.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Запеките лосось с травами 12-15 минут
2. Отварите киноа 15 минут
3. Обжарьте брокколи и морковь на оливковом масле
4. Подавайте с лимонным соком

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🐟 Лосось содержит омега-3 для синаптической пластичности
🌾 Киноа - медленные углеводы для стабильной энергии
🥦 Брокколи - сульфорафан для детокса"""
        return self.formatter.format_philosophy_content("🎯 НЕЙРО-ОБЕД ДЛЯ ФОКУСА", fallback, "lunch")

    def generate_neuro_dinner(self):
        """Генерация нейро-ужина для восстановления нервной системы"""
        prompt = """Создай рецепт ужина, который восстанавливает нервную систему и готовит мозг к качественному сну.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Ужин, который превращает вечернюю усталость в восстановительную силу"

🔬 НАУЧНЫЕ КОМПОНЕНТЫ:
- 😴 Триптофан для синтеза мелатонина
- 🧘 Магний для расслабления нервной системы
- 🛡️ Антиоксиданты для ночного восстановления
- 💪 Легкие белки для регенерации"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🌙 ВОССТАНАВЛИВАЮЩИЙ НЕЙРО-УЖИН", content, "dinner")
        
        fallback = """🐟 Треска с шалфеем и тушеными овощами

🎯 ИНГРЕДИЕНТЫ:
• 🐠 Треска - 150 г
• 🥬 Кабачок - 1 шт
• 🍆 Баклажан - 1 шт
• 🌿 Шалфей свежий - 3-4 листа
• 🍋 Лимонный сок - 1 ст.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Запеките треску с шалфеем 15 минут
2. Потушите овощи с травами 20 минут
3. Подавайте с лимонным соком

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🐠 Треска - легкий белок для восстановления
🌿 Шалфей улучшает когнитивные функции
🥬 Овощи - клетчатка для ночного детокса"""
        return self.formatter.format_philosophy_content("🌙 ВОССТАНАВЛИВАЮЩИЙ НЕЙРО-УЖИН", fallback, "dinner")

    def generate_neuro_dessert(self):
        """Генерация умного десерта для мозга"""
        prompt = """Создай рецепт десерта с авокадо, который улучшает когнитивные функции и поднимает настроение.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Сладкая пауза, которая делает тебя умнее"

🔬 НАУЧНЫЕ КОМПОНЕНТЫ:
- 🧠 Флавоноиды для улучшения памяти
- 😊 Триптофан для синтеза серотонина
- 🛡️ Антиоксиданты для защиты нейронов
- 💡 Магний для расслабления и фокуса"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🍫 УМНЫЙ ДЕСЕРТ ДЛЯ МОЗГА", content, "dessert")
        
        fallback = """🥑 Шоколадный мусс из авокадо

🎯 ИНГРЕДИЕНТЫ:
• 🥑 Авокадо - 2 спелых плода
• 🍫 Какао-порошок - 3 ст.л.
• 🍯 Мед - 2 ст.л.
• 🍌 Банан - 1 шт
• 🌰 Грецкие орехи - 30 г

🎯 ПРИГОТОВЛЕНИЕ:
1. Очистите авокадо и банан
2. Взбейте в блендере до кремообразной массы
3. Добавьте какао и мед, взбейте еще раз
4. Охладите 15 минут, посыпьте грецкими орехами

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🥑 Авокадо содержит олеиновую кислоту для мембран нейронов
🍫 Какао - флавоноиды для памяти
🌰 Грецкие орехи - омега-3 для синаптической пластичности"""
        return self.formatter.format_philosophy_content("🍫 УМНЫЙ ДЕСЕРТ ДЛЯ МОЗГА", fallback, "dessert")

    # 💪 ЭНЕРГИЯ И ТОНУС - ВТОРНИК
    def generate_energy_breakfast(self):
        """Генерация энерго-завтрака для активного дня"""
        prompt = """Создай рецепт завтрака, который заряжает клеточные электростанции - митохондрии.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Проснись с энергией, которой хватит на все твои амбиции"

🔬 КЛЮЧЕВЫЕ КОМПОНЕНТЫ:
- ⚡ Коэнзим Q10 для производства энергии
- 💪 Магний для АТФ синтеза
- 🔬 Витамины группы B для метаболизма
- 🎯 Железо для кислородного обмена"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("⚡ ЭНЕРГО-ЗАВТРАК ДЛЯ АКТИВНОГО ДНЯ", content, "breakfast")
        
        fallback = """🥣 Энергетическая овсянка с семенами

🎯 ИНГРЕДИЕНТЫ:
• 🌾 Овсяные хлопья - 50 г
• 🌰 Миндаль - 20 г
• 💎 Семена чиа - 1 ст.л.
• 🍌 Банан - 1 шт
• 🟤 Корица - ½ ч.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Залейте овсянку горячей водой на 5 минут
2. Добавьте нарезанный банан и семена чиа
3. Посыпьте миндалем и корицей

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🌾 Овсянка дает медленные углеводы для стабильной энергии
💎 Семена чиа - омега-3 для митохондрий
🟤 Корица регулирует уровень сахара в крови"""
        return self.formatter.format_philosophy_content("⚡ ЭНЕРГО-ЗАВТРАК ДЛЯ АКТИВНОГО ДНЯ", fallback, "breakfast")

    def generate_energy_lunch(self):
        """Генерация энерго-обеда для продуктивности"""
        prompt = """Создай рецепт обеда, который заряжает энергией на всю вторую половину дня.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Топливо для вечерних достижений и личных проектов"

🔬 КЛЮЧЕВЫЕ КОМПОНЕНТЫ:
- 💪 Постный белок для мышечного восстановления
- ⚡ Сложные углеводы для энергии
- 🌿 Клетчатка для стабильного пищеварения
- 🔬 Витамины группы B для метаболизма"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("⚡ ЭНЕРГО-ОБЕД ДЛЯ ПРОДУКТИВНОСТИ", content, "lunch")
        
        fallback = """🍗 Куриная грудка с булгуром и салатом

🎯 ИНГРЕДИЕНТЫ:
• 🍗 Куриная грудка - 150 г
• 🌾 Булгур - 80 г (сухой)
• 🥬 Салат айсберг - 100 г
• 🥒 Огурец - 1 шт
• 🫒 Оливковое масло - 1 ч.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Запеките куриную грудку с травами 20 минут
2. Отварите булгур 15 минут
3. Нарежьте свежие овощи для салата
4. Заправьте оливковым маслом

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🍗 Курица - источник белка для восстановления
🌾 Булгур - сложные углеводы для энергии
🥬 Свежие овощи - клетчатка для пищеварения"""
        return self.formatter.format_philosophy_content("⚡ ЭНЕРГО-ОБЕД ДЛЯ ПРОДУКТИВНОСТИ", fallback, "lunch")

    def generate_recovery_dinner(self):
        """Генерация восстанавливающего ужина для мышц"""
        prompt = """Создай рецепт ужина, который способствует восстановлению мышц и подготовке к следующему дню.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Ночное восстановление начинается с правильного ужина"

🔬 КЛЮЧЕВЫЕ КОМПОНЕНТЫ:
- 💪 Белки для мышечного восстановления
- ⚡ Медленные углеводы для ночной энергии
- 🛡️ Противовоспалительные компоненты
- 🧬 Аминокислоты для регенерации"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("💪 ВОССТАНАВЛИВАЮЩИЙ УЖИН", content, "dinner")
        
        fallback = """🦃 Индейка с печеными овощами

🎯 ИНГРЕДИЕНТЫ:
• 🦃 Грудка индейки - 150 г
• 🍠 Сладкий картофель - 1 шт
• 🥦 Брокколи - 200 г
• 🌿 Розмарин - 1 веточка
• 🥥 Кокосовое масло - 1 ч.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Запеките индейку с розмарином 25 минут
2. Запеките овощи с кокосовым маслом 30 минут
3. Подавайте с зеленым салатом

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🦃 Индейка содержит триптофан для сна
🍠 Сладкий картофель - сложные углеводы
🥦 Брокколи - сульфорафан для детокса"""
        return self.formatter.format_philosophy_content("💪 ВОССТАНАВЛИВАЮЩИЙ УЖИН", fallback, "dinner")

    # 🛡️ ДОЛГОЛЕТИЕ - СРЕДА
    def generate_longevity_breakfast(self):
        """Генерация завтрака долгожителя"""
        prompt = """Создай рецепт завтрака, который активирует гены долголетия и процессы клеточного обновления.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Каждое утро - возможность добавить здоровые годы к своей жизни"

🔬 ГЕРОПРОТЕКТОРЫ:
- 🧬 Ресвератрол для активации сиртуинов
- 🛡️ Куркумин против воспаления
- 🔬 Полифенолы для антиоксидантной защиты
- 💫 Спермидин для аутофагии"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🛡️ ЗАВТРАК ДОЛГОЖИТЕЛЯ", content, "breakfast")
        
        fallback = """🥣 Каша с куркумой и ягодами

🎯 ИНГРЕДИЕНТЫ:
• 🌾 Гречневая крупа - 50 г
• 🟡 Куркума - 1 ч.л.
• 🍓 Ягоды (замороженные) - 100 г
• 🌰 Грецкие орехи - 20 г
• 💧 Льняное масло - 1 ч.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Сварите гречневую кашу
2. Добавьте куркуму за 2 минуты до готовности
3. Подавайте с ягодами, орехами и льняным маслом

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🟡 Куркума содержит куркумин - мощный противовоспалительный агент
🍓 Ягоды - антоцианы против окислительного стресса
💧 Льняное масло - омега-3 для клеточных мембран"""
        return self.formatter.format_philosophy_content("🛡️ ЗАВТРАК ДОЛГОЖИТЕЛЯ", fallback, "breakfast")

    def generate_longevity_lunch(self):
        """Генерация обеда для долголетия"""
        prompt = """Создай рецепт обеда, который активирует гены долголетия и поддерживает клеточное здоровье.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Каждый обед - вклад в ваше здоровое будущее"

🔬 ГЕРОПРОТЕКТОРЫ:
- 🧬 Полифенолы против окислительного стресса
- 🛡️ Противовоспалительные компоненты
- 🌿 Клетчатка для микробиома
- 🔬 Антигликационные агенты"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🛡️ ОБЕД ДОЛГОЖИТЕЛЯ", content, "lunch")
        
        fallback = """🥬 Средиземноморская миска с нутом

🎯 ИНГРЕДИЕНТЫ:
• 🌱 Нут - 150 г (вареный)
• 🥑 Авокадо - ½ шт
• 🍅 Помидоры черри - 100 г
• 🥬 Руккола - 50 г
• 🫒 Оливковое масло extra virgin - 1 ст.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Смешайте нут с оливковым маслом
2. Добавьте нарезанный авокадо и помидоры
3. Выложите на подушку из рукколы
4. Посыпьте семенами кунжута

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🌱 Нут содержит клетчатку для микробиома
🥑 Авокадо - мононенасыщенные жиры для сердца
🫒 Оливковое масло - полифенолы против старения"""
        return self.formatter.format_philosophy_content("🛡️ ОБЕД ДОЛГОЖИТЕЛЯ", fallback, "lunch")

    def generate_longevity_dinner(self):
        """Генерация ужина для клеточного обновления"""
        prompt = """Создай рецепт ужина, который поддерживает процессы аутофагии и клеточного обновления.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Вечерний ритуал для утреннего обновления"

🔬 ГЕРОПРОТЕКТОРЫ:
- 🧬 Активаторы аутофагии
- 💪 Легкие белки для регенерации
- 🧠 Омега-3 для мембран нейронов
- 🛡️ Антиоксиданты для ночной защиты"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🛡️ УЖИН ДЛЯ КЛЕТОЧНОГО ОБНОВЛЕНИЯ", content, "dinner")
        
        fallback = """🥦 Суп-пюре из брокколи с куркумой

🎯 ИНГРЕДИЕНТЫ:
• 🥦 Брокколи - 300 г
• 🥬 Цветная капуста - 200 г
• 🟡 Куркума - 1 ч.л.
• 🥥 Кокосовое молоко - 100 мл
• 🟠 Имбирь свежий - 1 см

🎯 ПРИГОТОВЛЕНИЕ:
1. Отварите овощи 15 минут
2. Добавьте куркуму и имбирь
3. Взбейте блендером с кокосовым молоком
4. Прогрейте 5 минут

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🟡 Куркума содержит куркумин против воспаления
🥦 Брокколи - сульфорафан для детокса
🥥 Кокосовое молоко - среднецепочечные триглицериды для энергии"""
        return self.formatter.format_philosophy_content("🛡️ УЖИН ДЛЯ КЛЕТОЧНОГО ОБНОВЛЕНИЯ", fallback, "dinner")

    # 🍽️ ГАСТРОНОМИЯ - ЧЕТВЕРГ
    def generate_gastronomy_breakfast(self):
        """Генерация творческого завтрака"""
        prompt = """Создай рецепт завтрака ресторанного уровня, который доказывает: полезное может быть изысканным.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Начни день с гастрономического наслаждения, которое продлевает жизнь"

🎨 ЭЛЕМЕНТЫ ИЗЫСКАННОСТИ:
- Необычные сочетания вкусов
- Эстетика подачи
- Ресторанные техники
- Полезные ингредиенты премиум-класса"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🎨 ТВОРЧЕСКИЙ ЗАВТРАК", content, "breakfast")
        
        fallback = """🍳 Гренки с авокадо и яйцом-пашот

🎯 ИНГРЕДИЕНТЫ:
• 🍞 Хлеб цельнозерновой - 2 ломтика
• 🥑 Авокадо - 1 шт
• 🥚 Яйца - 2 шт
• 🥬 Руккола - 30 г
• ⚪ Семена кунжута - 1 ч.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Подсушите хлеб на сухой сковороде
2. Разомните авокадо с солью
3. Приготовьте яйца-пашот (3 минуты в кипящей воде)
4. Соберите: хлеб + авокадо + руккола + яйцо

💡 ШЕФ-СОВЕТ: Для идеального яйца-пашот добавьте в воду 1 ст.л. уксуса."""
        return self.formatter.format_philosophy_content("🎨 ТВОРЧЕСКИЙ ЗАВТРАК", fallback, "breakfast")

    def generate_gastronomy_lunch(self):
        """Генерация ресторанного обеда"""
        prompt = """Создай рецепт обеда ресторанного уровня, который сочетает изысканность и пользу для здоровья.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Обед, который превращает обычный день в гастрономическое событие"

🎨 ЭЛЕМЕНТЫ ИЗЫСКАННОСТИ:
- Сложные вкусовые профили
- Профессиональные техники приготовления
- Эстетика подачи
- Баланс текстур и вкусов"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🍽️ РЕСТОРАННЫЙ ОБЕД", content, "lunch")
        
        fallback = """🥩 Стейк из тунца с киноа и соусом песто

🎯 ИНГРЕДИЕНТЫ:
• 🐟 Стейк тунца - 180 г
• 🌾 Киноа - 100 г (сухая)
• 🥑 Авокадо - ½ шт
• 🍋 Лимон - 1 шт
• 🌿 Базилик свежий - 20 г

🎯 ПРИГОТОВЛЕНИЕ:
1. Обжарьте стейк тунца по 1 минуте с каждой стороны
2. Отварите киноа 15 минут
3. Приготовьте соус песто из базилика
4. Подавайте с дольками авокадо и лимоном

💡 ШЕФ-СОВЕТ: Тунец должен оставаться розовым внутри для максимальной пользы."""
        return self.formatter.format_philosophy_content("🍽️ РЕСТОРАННЫЙ ОБЕД", fallback, "lunch")

    def generate_gastronomy_dinner(self):
        """Генерация гастрономического ужина"""
        prompt = """Создай рецепт ужина ресторанного уровня для особого вечера, который сочетает наслаждение и пользу.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Вечер, когда еда становится искусством, а здоровье - роскошью"

🎨 ЭЛЕМЕНТЫ ИЗЫСКАННОСТИ:
- Сложные соусы и маринады
- Многослойность вкусов
- Эстетика сервировки
- Ресторанные техники приготовления"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🍽️ ГАСТРОНОМИЧЕСКИЙ УЖИН", content, "dinner")
        
        fallback = """🍗 Утка в апельсиновом глазури с пюре из цветной капусты

🎯 ИНГРЕДИЕНТЫ:
• 🦆 Утиная грудка - 200 г
• 🥬 Цветная капуста - 300 г
• 🍊 Апельсин - 1 шт
• 🍯 Мед - 1 ст.л.
• 🌿 Розмарин - 1 веточка

🎯 ПРИГОТОВЛЕНИЕ:
1. Обжарьте утиную грудку кожицей вниз 8 минут
2. Приготовьте пюре из цветной капусты
3. Сделайте глазурь из апельсинового сока и меда
4. Подавайте с розмарином

💡 ШЕФ-СОВЕТ: Дайте утке отдохнуть 5 минут перед подачей для сочности."""
        return self.formatter.format_philosophy_content("🍽️ ГАСТРОНОМИЧЕСКИЙ УЖИН", fallback, "dinner")

    # 📊 АНАЛИТИКА - ПЯТНИЦА
    def generate_analytical_breakfast(self):
        """Генерация аналитического завтрака"""
        prompt = """Создай рецепт завтрака, который помогает анализировать прошедшую неделю и планировать следующую.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Завтрак, который превращает опыт недели в планы на будущее"

🔬 КОГНИТИВНАЯ ПОДДЕРЖКА:
- 💡 Компоненты для ясности мышления
- 🎯 Нутриенты для принятия решений
- ⚡ Энергия для планирования
- 🛡️ Противовоспалительные для снижения стресса"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("📊 АНАЛИТИЧЕСКИЙ ЗАВТРАК", content, "breakfast")
        
        fallback = """🥣 Творожная масса с орехами и медом

🎯 ИНГРЕДИЕНТЫ:
• 🧀 Творог 5% - 150 г
• 🌰 Грецкие орехи - 30 г
• 🍯 Мед - 1 ст.л.
• 🍇 Изюм - 20 г
• 🍋 Лимонный сок - 1 ч.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Смешайте творог с медом и лимонным соком
2. Добавьте измельченные орехи и изюм
3. Подавайте с цельнозерновыми хлебцами

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🧀 Творог содержит тирозин для ясности мышления
🌰 Орехи - омега-3 для когнитивных функций
🍯 Мед - натуральную глюкозу для энергии мозга"""
        return self.formatter.format_philosophy_content("📊 АНАЛИТИЧЕСКИЙ ЗАВТРАК", fallback, "breakfast")

    def generate_analytical_lunch(self):
        """Генерация аналитического обеда"""
        prompt = """Создай рецепт обеда, который поддерживает ментальную ясность для принятия важных решений.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Обед, который очищает мысли и открывает новые перспективы"

🔬 КОГНИТИВНАЯ ПОДДЕРЖКА:
- 🧠 Компоненты для фокуса и концентрации
- 💡 Нутриенты для аналитического мышления
- ⚡ Стабильная энергия без сонливости
- 🛡️ Защита от стрессовых воздействий"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("📊 АНАЛИТИЧЕСКИЙ ОБЕД", content, "lunch")
        
        fallback = """🍲 Суп из чечевицы с шалфеем

🎯 ИНГРЕДИЕНТЫ:
• 🌱 Чечевица - 100 г (сухая)
• 🥕 Морковь - 1 шт
• 🧅 Лук - 1 шт
• 🌿 Шалфей свежий - 5-6 листьев
• 🫒 Оливковое масло - 1 ст.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Обжарьте лук и морковь 5 минут
2. Добавьте чечевицу и шалфей, залейте водой
3. Варите 25 минут до готовности
4. Подавайте с оливковым маслом

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🌱 Чечевица - медленные углеводы для стабильной энергии
🌿 Шалфей улучшает когнитивные функции
🫒 Оливковое масло - полезные жиры для мозга"""
        return self.formatter.format_philosophy_content("📊 АНАЛИТИЧЕСКИЙ ОБЕД", fallback, "lunch")

    def generate_planning_dinner(self):
        """Генерация ужина для планирования"""
        prompt = """Создай рецепт ужина, который помогает структурировать мысли и готовит к продуктивным выходным.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Ужин, который превращает хаос недели в ясный план действий"

🔬 КОГНИТИВНАЯ ПОДДЕРЖКА:
- 🧠 Компоненты для ментального расслабления
- 💡 Нутриенты для креативного мышления
- 😴 Подготовка к качественному сну
- 🛡️ Снижение недельного стресса"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("📊 УЖИН ДЛЯ ПЛАНИРОВАНИЯ", content, "dinner")
        
        fallback = """🍛 Рагу из индейки с овощами

🎯 ИНГРЕДИЕНТЫ:
• 🦃 Филе индейки - 150 г
• 🥦 Брокколи - 200 г
• 🥬 Цветная капуста - 200 г
• 🧄 Чеснок - 2 зубчика
• 🫒 Оливковое масло - 1 ст.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Обжарьте индейку с чесноком 10 минут
2. Добавьте овощи и тушите 20 минут
3. Подавайте с зеленью

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🦃 Индейка содержит триптофан для качественного сна
🥦 Овощи - клетчатка для детокса
🧄 Чеснок - противовоспалительные компоненты"""
        return self.formatter.format_philosophy_content("📊 УЖИН ДЛЯ ПЛАНИРОВАНИЯ", fallback, "dinner")

    # 🛒 УМНЫЕ ПОКУПКИ - СУББОТА
    def generate_smart_shopping_list(self):
        """Генерация умного чек-листа покупок"""
        season = self._get_current_season()
        
        shopping_list = f"""🛒 УМНЫЙ ЧЕК-ЛИСТ НА НЕДЕЛЮ

🎯 Основа для осознанного долголетия + сезонные продукты ({season})

🧠 ДЛЯ МОЗГА И НЕРВНОЙ СИСТЕМЫ:
• 🌰 Грецкие орехи - 200 г
• 🥑 Авокадо - 3-4 шт
• 🐟 Жирная рыба (лосось, скумбрия) - 500 г
• 🥚 Яйца - 10 шт
• 🍫 Темный шоколад 85% - 100 г

💪 ДЛЯ ЭНЕРГИИ И ТОНУСА:
• 🌾 Овсяные хлопья - 500 г
• 🍌 Бананы - 1 кг
• 💎 Семена чиа - 100 г
• 🍗 Куриная грудка - 1 кг
• 🌾 Гречневая крупа - 500 г

🛡️ ДЛЯ ДОЛГОЛЕТИЯ:
• 🟡 Куркума - 50 г
• 🟠 Имбирь - 100 г
• 🧄 Чеснок - 3 головки
• 🍓 Ягоды (замороженные) - 500 г
• 🥬 Зеленые овощи - 1 кг

🍽️ ДЛЯ ГАСТРОНОМИЧЕСКОГО НАСЛАЖДЕНИЯ:
• 🌶️ Специи (корица, кардамон, мускат)
• 🍯 Натуральный мед - 300 г
• 🥥 Кокосовое молоко - 400 мл
• 🫒 Оливковое масло - 500 мл

💡 СОВЕТЫ ОТ ШЕФ-ПОВАРА:
• 🛒 Покупайте сезонные местные продукты
• 📖 Читайте составы - избегайте рафинированного сахара
• 📅 Планируйте меню на неделю вперед
• ❄️ Храните орехи и семена в холодильнике

🎯 ФИЛОСОФИЯ ПОКУПОК:
Каждый продукт в вашей корзине - это инвестиция в ваше долголетие и качество жизни!

#чеклист #умныепокупки #{season}"""
        
        return shopping_list

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

    # 🍳 ВОСКРЕСНЫЙ БРАНЧ
    def generate_sunday_brunch(self):
        """Генерация воскресного бранча"""
        prompt = """Создай рецепт бранча, который становится ритуалом подготовки к новой неделе.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Воскресный бранч - твой стратегический ресурс для успешной недели"

🎨 ЭЛЕМЕНТЫ РИТУАЛА:
- Блюда, требующие осознанного приготовления
- Ингредиенты для ментальной подготовки
- Сочетания для эмоционального баланса
- Техники, развивающие кулинарные навыки"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🍳 ВОСКРЕСНЫЙ БРАНЧ-РИТУАЛ", content, "brunch")
        
        fallback = """🥞 Панкейки из цельнозерновой муки с ягодным соусом

🎯 ИНГРЕДИЕНТЫ:
• 🌾 Мука цельнозерновая - 150 г
• 🥚 Яйца - 2 шт
• 🥛 Кефир - 200 мл
• 🧪 Разрыхлитель - 1 ч.л.
• 🍓 Ягоды (замороженные) - 200 г
• 🍯 Мед - 2 ст.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Смешайте сухие ингредиенты
2. Добавьте яйца и кефир, замесите тесто
3. Жарьте на антипригарной сковороде по 2-3 минуты с каждой стороны
4. Для соуса разогрейте ягоды с медом

💡 РИТУАЛ ОСОЗНАННОСТИ: Готовьте в тишине, концентрируясь на каждом действии. Это медитация, которая насыщает не только тело, но и душу."""
        return self.formatter.format_philosophy_content("🍳 ВОСКРЕСНЫЙ БРАНЧ-РИТУАЛ", fallback, "brunch")

    # 🔬 НАУЧНЫЙ КОНТЕНТ
    def generate_science_content(self):
        """Генерация научного контента"""
        prompt = """Представь научный факт о питании и долголетии, который можно применить сегодня же.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Наука, которая меняет твое отношение к еде прямо сейчас"

🎯 ТРЕБОВАНИЯ:
- Только доказанные исследования
- Практическое применение
- Объяснение механизма действия
- Опора на авторитетные источники"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🔬 НАУКА ОСОЗНАННОГО ДОЛГОЛЕТИЯ", content, "science")
        
        fallback = """🏆 Научный факт: Интервальное голодание активирует аутофагию

🎯 ЧТО ЭТО ТАКОЕ: Аутофагия - процесс очищения клеток от поврежденных компонентов, открытый японским ученым Ёсинори Осуми (Нобелевская премия 2016).

🔬 КАК РАБОТАЕТ: При 16-часовом перерыве в питании клетки начинают "поедать" собственные поврежденные белки и органеллы, обновляясь на молекулярном уровне.

💡 ПРАКТИЧЕСКОЕ ПРИМЕНЕНИЕ: Попробуйте окончить ужин в 20:00 и позавтракать в 12:00 следующего дня.

🎯 ОЖИДАЕМЫЙ ЭФФЕКТ: Улучшение когнитивных функций, замедление старения, снижение риска возрастных заболеваний.

💡 ПРОСТЫЕ ШАГИ: Начните с 12-часового перерыва, постепенно увеличивая до 16 часов."""
        return self.formatter.format_philosophy_content("🔬 НАУКА ОСОЗНАННОГО ДОЛГОЛЕТИЯ", fallback, "science")

    # 💡 СОВЕТЫ ЭКСПЕРТОВ
    def generate_expert_advice(self):
        """Генерация советов экспертов"""
        prompt = """Сформулируй принцип осознанного питания, который становится философией на всю жизнь.

🎯 ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР: "Принцип, который превращает еду из привычки в инструмент роста"

🎯 ТРЕБОВАНИЯ К ПРИНЦИПУ:
- Универсальность применения
- Научная обоснованность
- Простота понимания
- Глубина воздействия"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("💡 ПРИНЦИПЫ УМНОГО ПИТАНИЯ", content, "advice")
        
        fallback = """🎯 Принцип: "Ешьте цвета радуги"

🎯 ФОРМУЛИРОВКА: Каждый день включайте в рацион продукты всех цветов радуги - красные, оранжевые, желтые, зеленые, синие, фиолетовые.

🔬 НАУЧНОЕ ОБОСНОВАНИЕ: Разные цвета овощей и фруктов указывают на наличие различных фитонутриентов:
• 🔴 Красные - ликопин (против рака)
• 🟠 Оранжевые - бета-каротин (зрение)
• 🟢 Зеленые - лютеин (мозг)
• 🔵 Синие - антоцианы (сердце)

💡 ПРАКТИЧЕСКОЕ ПРИМЕНЕНИЕ: Сделайте свой обед разноцветным - салат из помидоров, моркови, перца, огурцов и капусты.

🎯 РЕЗУЛЬТАТЫ: Укрепление иммунной системы, снижение воспаления, защита от хронических заболеваний.

💡 ПРОСТОЙ ШАГ: Добавьте хотя бы 3 разных цвета в каждый основной прием пищи."""
        return self.formatter.format_philosophy_content("💡 ПРИНЦИПЫ УМНОГО ПИТАНИЯ", fallback, "advice")

# Менеджер контента для правильного выбора методов
class ContentManager:
    """Менеджер для выбора правильных методов генерации контента"""
    
    @staticmethod
    def get_content_for_time(kemerovo_time_str, weekday):
        """Возвращает правильный метод генератора для времени и дня недели"""
        hour = int(kemerovo_time_str.split(':')[0])
        
        # Определяем тип приема пищи по времени
        if 5 <= hour < 11:  # 05:00 - 10:59 - завтрак
            meal_type = "breakfast"
        elif 11 <= hour < 16:  # 11:00 - 15:59 - обед
            meal_type = "lunch" 
        elif 16 <= hour < 18:  # 16:00 - 17:59 - полдник/десерт
            meal_type = "dessert"
        else:  # 18:00 - 04:59 - ужин
            meal_type = "dinner"
        
        # ПОЛНЫЙ маппинг методов по дням недели и типам пищи
        content_mapping = {
            'monday': {
                'breakfast': 'generate_neuro_breakfast',
                'lunch': 'generate_neuro_lunch',
                'dessert': 'generate_neuro_dessert',
                'dinner': 'generate_neuro_dinner'
            },
            'tuesday': {
                'breakfast': 'generate_energy_breakfast',
                'lunch': 'generate_energy_lunch',
                'dessert': 'generate_neuro_dessert',
                'dinner': 'generate_recovery_dinner'
            },
            'wednesday': {
                'breakfast': 'generate_longevity_breakfast',
                'lunch': 'generate_longevity_lunch',
                'dessert': 'generate_neuro_dessert', 
                'dinner': 'generate_longevity_dinner'
            },
            'thursday': {
                'breakfast': 'generate_gastronomy_breakfast',
                'lunch': 'generate_gastronomy_lunch',
                'dessert': 'generate_neuro_dessert',
                'dinner': 'generate_gastronomy_dinner'
            },
            'friday': {
                'breakfast': 'generate_analytical_breakfast', 
                'lunch': 'generate_analytical_lunch',
                'dessert': 'generate_neuro_dessert',
                'dinner': 'generate_planning_dinner'
            },
            'saturday': {
                'breakfast': 'generate_energy_breakfast',
                'lunch': 'generate_gastronomy_lunch',
                'dessert': 'generate_neuro_dessert',
                'dinner': 'generate_gastronomy_dinner'
            },
            'sunday': {
                'breakfast': 'generate_sunday_brunch',
                'lunch': 'generate_gastronomy_lunch',  
                'dessert': 'generate_neuro_dessert',
                'dinner': 'generate_planning_dinner'
            }
        }
        
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        day_key = days[weekday]
        
        return content_mapping.get(day_key, {}).get(meal_type, 'generate_energy_breakfast')

    @staticmethod
    def get_current_meal_type():
        """Определяет текущий тип приема пищи по времени Кемерово"""
        kemerovo_now = datetime.now(Config.KEMEROVO_TIMEZONE)
        hour = kemerovo_now.hour
        
        if 5 <= hour < 11:
            return "breakfast", "🍳 Завтрак"
        elif 11 <= hour < 16:
            return "lunch", "🍲 Обед"
        elif 16 <= hour < 18:
            return "dessert", "🍰 Десерт"
        else:
            return "dinner", "🍽️ Ужин"

# Расписание публикаций
class ContentScheduler:
    def __init__(self):
        # Полное расписание на всю неделю в времени Кемерово (UTC+7)
        self.kemerovo_schedule = {
            'monday': {
                "07:00": {"type": "neuro_breakfast", "name": "🧠 Нейрозавтрак для ясности ума"},
                "12:00": {"type": "neuro_lunch", "name": "🎯 Нейро-обед для фокуса и концентрации"},
                "16:00": {"type": "brain_science", "name": "🔬 Научный факт о мозге и питании"},
                "17:00": {"type": "neuro_dessert", "name": "🍫 Умный десерт для когнитивных функций"},
                "19:00": {"type": "neuro_dinner", "name": "🌙 Восстанавливающий нейро-ужин для нервной системы"},
                "21:00": {"type": "evening_biohack", "name": "💫 Вечерний биохакинг для мозга"}
            },
            'tuesday': {
                "07:00": {"type": "energy_breakfast", "name": "⚡ Энерго-завтрак для активного дня"},
                "12:00": {"type": "energy_lunch", "name": "⚡ Энерго-обед для продуктивности"},
                "16:00": {"type": "energy_science", "name": "🔬 Наука энергии и метаболизма"},
                "17:00": {"type": "energy_dessert", "name": "🍓 Энергетический десерт"},
                "19:00": {"type": "recovery_dinner", "name": "💪 Восстанавливающий ужин для мышц"},
                "21:00": {"type": "energy_tips", "name": "💡 Принципы поддержания энергии"}
            },
            'wednesday': {
                "07:00": {"type": "longevity_breakfast", "name": "🛡️ Завтрак долгожителя"},
                "12:00": {"type": "longevity_lunch", "name": "🛡️ Обед для долголетия"},
                "16:00": {"type": "longevity_science", "name": "🔬 Наука anti-age питания"},
                "17:00": {"type": "anti_age_dessert", "name": "🍇 Антиэйдж десерт"},
                "19:00": {"type": "longevity_dinner", "name": "🛡️ Ужин для клеточного обновления"},
                "21:00": {"type": "longevity_principles", "name": "💡 Принципы долголетия"}
            },
            'thursday': {
                "07:00": {"type": "gastronomy_breakfast", "name": "🎨 Творческий завтрак ресторанного уровня"},
                "12:00": {"type": "gastronomy_lunch", "name": "🍽️ Ресторанный обед с пользой"},
                "16:00": {"type": "taste_science", "name": "🔬 Наука вкуса и наслаждения"},
                "17:00": {"type": "michelin_dessert", "name": "🎭 Шеф-десерт от Мишлен"},
                "19:00": {"type": "gastronomy_dinner", "name": "🍽️ Гастрономический ужин"},
                "21:00": {"type": "enjoyment_principles", "name": "💡 Искусство осознанного наслаждения"}
            },
            'friday': {
                "07:00": {"type": "analytical_breakfast", "name": "📊 Аналитический завтрак для планирования"},
                "12:00": {"type": "analytical_lunch", "name": "📊 Аналитический обед для принятия решений"},
                "16:00": {"type": "results_science", "name": "🔬 Наука продуктивности и питания"},
                "17:00": {"type": "reflection_dessert", "name": "🍍 Десерт для осмысления недели"},
                "19:00": {"type": "planning_dinner", "name": "📊 Ужин для планирования на выходные"},
                "21:00": {"type": "weekly_planning", "name": "💡 Планирование питания на следующую неделю"}
            },
            'saturday': {
                "07:00": {"type": "weekend_breakfast", "name": "🥗 Субботний завтрак для семьи"},
                "10:00": {"type": "shopping_list", "name": "🛒 Умный чек-лист покупок на неделю"},
                "12:00": {"type": "family_lunch", "name": "🍲 Семейный обед"},
                "15:00": {"type": "visual_content", "name": "🎨 Визуальный контент (инфографика)"},
                "17:00": {"type": "weekend_dessert", "name": "🧁 Субботний десерт"},
                "19:00": {"type": "weekend_dinner", "name": "🌙 Субботний ужин"},
                "21:00": {"type": "weekend_tips", "name": "💡 Советы для выходных"}
            },
            'sunday': {
                "07:00": {"type": "sunday_brunch", "name": "🍳 Воскресный бранч-ритуал"},
                "12:00": {"type": "sunday_lunch", "name": "🥘 Воскресный обед"},
                "17:00": {"type": "sunday_dessert", "name": "🍮 Воскресный десерт"},
                "18:00": {"type": "sunday_dinner", "name": "🌙 Воскресный ужин для подготовки к неделе"},
                "21:00": {"type": "weekly_motivation", "name": "🎯 Мотивация и настрой на новую неделю"}
            }
        }
        
        self.is_running = False
        logger.info("✅ Инициализирован планировщик контента с новым визуальным форматом")

    def _schedule_daily_content(self, day, server_time, event):
        """Планирует контент для конкретного дня"""
        def job():
            try:
                current_times = TimeZoneConverter.get_current_times()
                logger.info(f"🕒 Выполнение: {event['name']} в {current_times['kemerovo_time']}")
                
                # Получаем текущий день недели и время
                kemerovo_now = datetime.now(Config.KEMEROVO_TIMEZONE)
                weekday = kemerovo_now.weekday()
                current_time_str = kemerovo_now.strftime('%H:%M')
                
                # Определяем правильный метод генерации через ContentManager
                method_name = ContentManager.get_content_for_time(current_time_str, weekday)
                
                if hasattr(content_gen, method_name):
                    method = getattr(content_gen, method_name)
                    content = method()
                    logger.info(f"✅ Используется метод: {method_name} для времени {current_time_str}")
                else:
                    logger.error(f"❌ Метод {method_name} не найден, используем fallback")
                    content = content_gen.generate_energy_breakfast()  # Fallback
                
                if content:
                    meal_type, meal_name = ContentManager.get_current_meal_type()
                    content_with_time = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']} ({meal_name})"
                    success = elite_channel.send_to_telegram(content_with_time)
                    if success:
                        logger.info(f"✅ Успешная публикация: {event['name']} -> {method_name}")
                    else:
                        logger.error(f"❌ Ошибка публикации: {event['name']}")
            except Exception as e:
                logger.error(f"❌ Ошибка в задаче планировщика: {e}")

        # Планируем задачу на конкретный день и время
        day_mapping = {
            'monday': schedule.every().monday,
            'tuesday': schedule.every().tuesday,
            'wednesday': schedule.every().wednesday,
            'thursday': schedule.every().thursday,
            'friday': schedule.every().friday,
            'saturday': schedule.every().saturday,
            'sunday': schedule.every().sunday
        }
        
        if day in day_mapping:
            day_mapping[day].at(server_time).do(job)
            logger.info(f"✅ Запланировано: {day} {server_time} - {event['name']}")
        else:
            logger.error(f"❌ Неизвестный день недели: {day}")

    def start_scheduler(self):
        """Запуск планировщика"""
        if self.is_running:
            return
        
        logger.info("🚀 Запуск планировщика контента с новым визуальным форматом...")
        
        # Планируем основной контент для каждого дня
        for day, day_schedule in self.kemerovo_schedule.items():
            for kemerovo_time, event in day_schedule.items():
                server_time = TimeZoneConverter.kemerovo_to_server_time(kemerovo_time)
                if server_time:
                    self._schedule_daily_content(day, server_time, event)
                    logger.info(f"📅 Расписание: {day} - Кемерово {kemerovo_time} -> Сервер {server_time} - {event['name']}")
        
        # Планируем ежедневный отчет
        self._schedule_analytics_reports()
        
        self.is_running = True
        self._run_scheduler()

    def _schedule_analytics_reports(self):
        """Планирование аналитических отчетов"""
        public_report_time = TimeZoneConverter.kemerovo_to_server_time("09:00")
        
        def public_analytics_job():
            try:
                logger.info("📊 Генерация публичного отчета")
                report = channel_analytics.generate_public_report()
                elite_channel.send_to_telegram(report)
            except Exception as e:
                logger.error(f"❌ Ошибка генерации отчета: {e}")
        
        if public_report_time:
            schedule.every().day.at(public_report_time).do(public_analytics_job)
            logger.info(f"✅ Запланирован публичный отчет на {public_report_time}")

    def _run_scheduler(self):
        """Запускает фоновый поток планировщика"""
        def run_scheduler():
            while self.is_running:
                try:
                    schedule.run_pending()
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"❌ Ошибка в потоке планировщика: {e}")
                    time.sleep(60)
        
        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        logger.info("✅ Планировщик запущен в фоновом потоке")

    def get_next_event(self):
        """Получает следующее событие с учетом текущего дня недели"""
        try:
            current_kemerovo = datetime.now(Config.KEMEROVO_TIMEZONE)
            current_time_str = current_kemerovo.strftime('%H:%M')
            current_weekday = current_kemerovo.weekday()
            
            days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            current_day = days[current_weekday]
            
            # Ищем следующее событие сегодня
            today_schedule = self.kemerovo_schedule.get(current_day, {})
            times_today = sorted([t for t in today_schedule.keys() if t >= current_time_str])
            
            if times_today:
                next_kemerovo_time = times_today[0]
                next_event = today_schedule[next_kemerovo_time]
                next_server_time = TimeZoneConverter.kemerovo_to_server_time(next_kemerovo_time)
                return next_server_time, next_kemerovo_time, next_event
            
            # Если сегодня событий нет, ищем завтра
            next_weekday = (current_weekday + 1) % 7
            next_day = days[next_weekday]
            next_day_schedule = self.kemerovo_schedule.get(next_day, {})
            
            if next_day_schedule:
                next_kemerovo_time = min(next_day_schedule.keys())
                next_event = next_day_schedule[next_kemerovo_time]
                next_server_time = TimeZoneConverter.kemerovo_to_server_time(next_kemerovo_time)
                return next_server_time, next_kemerovo_time, next_event
            
            return "17:00", "17:00", {"name": "Следующий пост", "type": "unknown"}
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения следующего события: {e}")
            return "17:00", "17:00", {"name": "Следующий пост", "type": "unknown"}

    def _get_day_theme(self, weekday):
        """Возвращает тему дня недели"""
        themes = {
            0: "🧠 Нейропитание - фокус на мозг и когнитивные функции",
            1: "💪 Энергия и тонус - заряд энергии для достижений", 
            2: "🛡️ Долголетие - стратегии здоровой долгой жизни",
            3: "🍽️ Гастрономическое наслаждение - изысканность с пользой",
            4: "📊 Аналитика и планирование - результаты и планы",
            5: "🛒 Умные покупки + рецепты - подготовка к неделе",
            6: "🍳 Воскресные ритуалы - настрой на новую неделю"
        }
        return themes.get(weekday, "🎯 Осознанное питание")

# Инициализация компонентов с проверкой безопасности
try:
    elite_channel = EliteChannel()
    content_gen = ContentGenerator()
    content_scheduler = ContentScheduler()
    channel_analytics = ChannelAnalytics(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHANNEL)

    # Запускаем планировщик при старте
    content_scheduler.start_scheduler()
    logger.info("✅ Все компоненты инициализированы")
    
    current_times = TimeZoneConverter.get_current_times()
    logger.info(f"🌍 Текущее время сервера: {current_times['server_time']}")
    logger.info(f"🌍 Время Кемерово: {current_times['kemerovo_time']}")
    
    member_count = channel_analytics.get_member_count()
    logger.info(f"📊 Начальное количество подписчиков: {member_count}")
    
except Exception as e:
    logger.error(f"❌ Ошибка инициализации: {e}")
    exit(1)

# Маршруты Flask
@app.route('/')
def index():
    """Главная страница"""
    try:
        next_server_time, next_kemerovo_time, next_event = content_scheduler.get_next_event()
        connection_info = elite_channel.test_connection()
        current_times = TimeZoneConverter.get_current_times()
        member_count = channel_analytics.get_member_count()
        
        # Получаем русское название дня недели
        weekday_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        current_weekday = datetime.now(Config.KEMEROVO_TIMEZONE).weekday()
        current_day_name = weekday_names[current_weekday]
        
        html = f"""
        <html>
            <head>
                <title>Система управления @ppsupershef</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                    .container {{ max-width: 1200px; margin: 0 auto; }}
                    .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
                    .stats-card {{ background: #3498db; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .time-info {{ background: #27ae60; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .btn {{ display: inline-block; padding: 10px 20px; margin: 5px; background: #3498db; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; }}
                    .btn-danger {{ background: #e74c3c; }}
                    .btn-success {{ background: #27ae60; }}
                    .btn-warning {{ background: #f39c12; }}
                    .btn-info {{ background: #17a2b8; }}
                    .content-section {{ background: white; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                    .quick-actions {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 20px 0; }}
                    .content-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 20px 0; }}
                    .form-group {{ margin: 10px 0; }}
                    input, textarea, select {{ width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 5px; }}
                    .day-info {{ background: #9b59b6; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .diagnosis-result {{ background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 5px; padding: 15px; margin: 10px 0; }}
                    .check-item {{ margin: 5px 0; padding: 5px; border-radius: 3px; }}
                    .check-success {{ background: #d4edda; color: #155724; }}
                    .check-error {{ background: #f8d7da; color: #721c24; }}
                    .check-warning {{ background: #fff3cd; color: #856404; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎪 Система управления @ppsupershef</h1>
                        <p>🎯 ФИЛОСОФИЯ: Осознанное питание как инвестиция в энергичную, долгую и продуктивную жизнь</p>
                    </div>
                    
                    <div class="day-info">
                        <h2>📅 Сегодня: {current_day_name}</h2>
                        <p>🎯 Тема дня: {content_scheduler._get_day_theme(current_weekday)}</p>
                    </div>
                    
                    <div class="quick-actions">
                        <button class="btn" onclick="testChannel()">📊 Статистика</button>
                        <button class="btn" onclick="testConnection()">Тест канала</button>
                        <button class="btn btn-info" onclick="diagnoseChannel()">🔧 Диагностика канала</button>
                        <button class="btn" onclick="showDebug()">Отладка</button>
                        <button class="btn" onclick="healthCheck()">Health Check</button>
                        <button class="btn" onclick="showFormatPreview()">Предпросмотр формата</button>
                        <button class="btn" onclick="sendPoll()">Отправить опрос</button>
                        <button class="btn" onclick="sendVisualContent()">Визуальный контент</button>
                        <button class="btn" onclick="sendShoppingList()">Чек-лист покупок</button>
                        <button class="btn btn-success" onclick="sendPublicReport()">📨 Отчет статистики</button>
                    </div>
                    
                    <div class="content-section">
                        <h2>📤 Отправка контента</h2>
                        <div class="content-grid">
                            <button class="btn" onclick="sendContent('breakfast')">🍳 Завтрак</button>
                            <button class="btn" onclick="sendContent('lunch')">🍲 Обед</button>
                            <button class="btn" onclick="sendContent('science')">🔬 Наука</button>
                            <button class="btn" onclick="sendContent('interval')">⏱️ Интервал</button>
                            <button class="btn" onclick="sendContent('dinner')">🍽️ Ужин</button>
                            <button class="btn" onclick="sendContent('advice')">💡 Советы экспертов</button>
                        </div>
                        
                        <div class="form-group">
                            <h3>✍️ Ручной ввод контента</h3>
                            <textarea id="manualContent" rows="6" placeholder="Введите текст сообщения для Telegram..."></textarea>
                            <button class="btn btn-success" onclick="sendManualContent()">📤 Отправить в канал</button>
                        </div>
                    </div>
                    
                    <div id="diagnosisResult" class="diagnosis-result" style="display: none;">
                        <h3>🔧 Результаты диагностики канала</h3>
                        <div id="diagnosisContent"></div>
                    </div>
                    
                    <div class="stats-card">
                        <h2>📊 СТАТИСТИКА КАНАЛА</h2>
                        <p><strong>👥 Подписчиков: {member_count}</strong></p>
                        <p><strong>📈 Контент: 45 постов/неделя</strong></p>
                        <p><strong>🎯 Философия: Осознанное долголетие через правильное питание</strong></p>
                    </div>
                    
                    <div class="time-info">
                        <h3>🌍 ИНФОРМАЦИЯ О ВРЕМЕНИ</h3>
                        <p>Сервер: <strong>{current_times['server_time']}</strong> • Кемерово: <strong>{current_times['kemerovo_time']}</strong></p>
                        <p>Следующая публикация: <strong>{next_kemerovo_time} - {next_event['name']}</strong></p>
                    </div>
                </div>

                <script>
                    function testConnection() {{
                        fetch('/test-channel')
                            .then(response => response.json())
                            .then(data => alert('Результат теста: ' + (data.status === 'success' ? '✅ Успешно' : '❌ Ошибка')));
                    }}

                    function healthCheck() {{
                        fetch('/health')
                            .then(response => response.json())
                            .then(data => alert('Статус системы: ' + (data.status === 'healthy' ? '✅ Здорова' : '❌ Проблемы')));
                    }}

                    function showDebug() {{
                        fetch('/debug')
                            .then(response => response.json())
                            .then(data => alert('Отладка: ' + JSON.stringify(data, null, 2)));
                    }}

                    function testChannel() {{
                        fetch('/test-channel')
                            .then(response => response.json())
                            .then(data => alert('Тест канала: ' + (data.status === 'success' ? '✅ Успешно' : '❌ Ошибка')));
                    }}

                    function diagnoseChannel() {{
                        fetch('/diagnose-channel')
                            .then(response => response.json())
                            .then(data => {{
                                const resultDiv = document.getElementById('diagnosisResult');
                                const contentDiv = document.getElementById('diagnosisContent');
                                
                                let html = `<h4>${data.summary}</h4>`;
                                html += `<p><strong>Время диагностики:</strong> ${data.timestamp}</p>`;
                                html += `<h5>Проверки:</h5>`;
                                
                                data.checks.forEach(check => {{
                                    let statusClass = 'check-warning';
                                    if (check.status.includes('✅')) statusClass = 'check-success';
                                    if (check.status.includes('❌')) statusClass = 'check-error';
                                    
                                    html += `<div class="check-item ${statusClass}">
                                        <strong>${check.check}</strong>: ${check.status} - ${check.details}
                                    </div>`;
                                }});
                                
                                contentDiv.innerHTML = html;
                                resultDiv.style.display = 'block';
                                
                                // Прокрутка к результатам
                                resultDiv.scrollIntoView({{ behavior: 'smooth' }});
                            }});
                    }}

                    function sendPublicReport() {{
                        fetch('/send-public-report')
                            .then(response => response.json())
                            .then(data => alert('Отчет: ' + (data.status === 'success' ? '✅ Отправлен' : '❌ Ошибка')));
                    }}

                    function sendPoll() {{
                        fetch('/send-poll')
                            .then(response => response.json())
                            .then(data => alert('Опрос: ' + (data.status === 'success' ? '✅ Создан' : '❌ Ошибка')));
                    }}

                    function sendVisualContent() {{
                        fetch('/send-visual-content')
                            .then(response => response.json())
                            .then(data => alert('Визуальный контент: ' + (data.status === 'success' ? '✅ Отправлен' : '❌ Ошибка')));
                    }}

                    function sendShoppingList() {{
                        fetch('/send-shopping-list')
                            .then(response => response.json())
                            .then(data => alert('Чек-лист: ' + (data.status === 'success' ? '✅ Отправлен' : '❌ Ошибка')));
                    }}

                    function showFormatPreview() {{
                        fetch('/format-preview')
                            .then(response => response.json())
                            .then(data => {{
                                if (data.status === 'success') {{
                                    alert('Предпросмотр формата отправлен в канал');
                                }} else {{
                                    alert('Ошибка: ' + data.message);
                                }}
                            }});
                    }}

                    function sendContent(type) {{
                        const endpoints = {{
                            'breakfast': '/send-breakfast',
                            'lunch': '/send-lunch', 
                            'science': '/send-science',
                            'interval': '/send-interval',
                            'dinner': '/send-dinner',
                            'advice': '/send-advice'
                        }};

                        if (endpoints[type]) {{
                            fetch(endpoints[type])
                                .then(response => response.json())
                                .then(data => alert('Контент отправлен: ' + (data.status === 'success' ? '✅ Успешно' : '❌ Ошибка')));
                        }}
                    }}

                    function sendManualContent() {{
                        const content = document.getElementById('manualContent').value;
                        if (!content) {{
                            alert('Введите текст сообщения');
                            return;
                        }}

                        fetch('/send-manual-content', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                            }},
                            body: JSON.stringify({{ content: content }})
                        }})
                        .then(response => response.json())
                        .then(data => {{
                            if (data.status === 'success') {{
                                alert('✅ Сообщение отправлено в канал');
                                document.getElementById('manualContent').value = '';
                            }} else {{
                                alert('❌ Ошибка: ' + data.message);
                            }}
                        }});
                    }}
                </script>
            </body>
        </html>
        """
        return html
        
    except Exception as e:
        logger.error(f"❌ Ошибка в главной странице: {e}")
        return f"Ошибка: {str(e)}"

@app.route('/send-public-report')
def send_public_report():
    """Отправка публичного отчета"""
    try:
        report = channel_analytics.generate_public_report()
        success = elite_channel.send_to_telegram(report)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/test-channel')
def test_channel():
    """Тестирование канала"""
    current_times = TimeZoneConverter.get_current_times()
    test_message = f"""🎪 КЛУБ ОСОЗНАННОГО ДОЛГОЛЕТИЯ ЧЕРЕЗ ПРАВИЛЬНОЕ ПИТАНИЕ

🎯 ТЕСТ: Система работает с новым визуальным форматом!

🎯 Новая философия контента активирована:

🧠 Нейропитание - пища для ясности ума
💪 Энергия - топливо для достижений  
🛡️ Долголетие - стратегии здоровой жизни
🍽️ Гастрономия - наслаждение с пользой

🤖 Автопостинг: ✅ Активен
🎯 Контент-план: 45 постов/неделя
💫 Философия: Осознанное питание как инвестиция в качество жизни

🎯 Присоединяйтесь к клубу тех, кто выбирает осознанность!

🕐 Опубликовано: {current_times['kemerovo_time']}"""
    
    success = elite_channel.send_to_telegram(test_message)
    return jsonify({"status": "success" if success else "error"})

@app.route('/diagnose-channel')
def diagnose_channel():
    """Полная диагностика канала"""
    try:
        diagnosis = elite_channel.diagnose_channel()
        return jsonify(diagnosis)
    except Exception as e:
        return jsonify({
            "status": "error",
            "checks": [{"check": "Общая диагностика", "status": "❌ Ошибка", "details": f"Исключение: {str(e)}"}],
            "summary": "❌ Ошибка диагностики",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

@app.route('/health')
def health_check():
    """Проверка здоровья"""
    connection = elite_channel.test_connection()
    current_times = TimeZoneConverter.get_current_times()
    member_count = channel_analytics.get_member_count()
    
    return jsonify({
        "status": "healthy",
        "philosophy": "🎪 Клуб Осознанного Долголетия через Правильное Питание",
        "member_count": member_count,
        "scheduler_running": content_scheduler.is_running,
        "time_info": current_times
    })

@app.route('/debug')
def debug():
    """Страница отладки"""
    connection_test = elite_channel.test_connection()
    current_times = TimeZoneConverter.get_current_times()
    member_count = channel_analytics.get_member_count()
    
    return jsonify({
        "status": "active",
        "philosophy": "🎯 Осознанное долголетие через правильное питание",
        "content_plan": "45 постов/неделя",
        "member_count": member_count,
        "scheduler_status": "running" if content_scheduler.is_running else "stopped",
        "time_info": current_times
    })

@app.route('/send-poll')
def send_poll():
    """Отправка опроса"""
    try:
        success = elite_channel.send_poll()
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-visual-content')
def send_visual_content():
    """Отправка визуального контента"""
    try:
        success = elite_channel.send_visual_content()
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-shopping-list')
def send_shopping_list():
    """Отправка чек-листа покупок"""
    try:
        content = content_gen.generate_smart_shopping_list()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/format-preview')
def format_preview():
    """Предпросмотр формата контента"""
    try:
        preview_content = """🎪 КЛУБ ОСОЗНАННОГО ДОЛГОЛЕТИЯ ЧЕРЕЗ ПРАВИЛЬНОЕ ПИТАНИЕ

🎯 Станьте версией себя, которой восхищаетесь

🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА

🥑 Омлет с авокадо и шпинатом

🎯 ИНГРЕДИЕНТЫ:
• 🥚 Яйца - 2 шт
• 🥑 Авокадо - ½ шт  
• 🥬 Шпинат - 50 г
• 🌰 Грецкие орехи - 20 г
• 🫒 Оливковое масло - 1 ч.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Взбейте яйца с щепоткой соли
2. Обжарьте шпинат на оливковом масле 2 минуты
3. Влейте яйца, готовьте на среднем огне 5-7 минут
4. Подавайте с ломтиками авокадо и грецкими орехами

💡 НАУЧНОЕ ОБОСНОВАНИЕ: 
🥑 Авокадо содержит омега-9 для мембран нейронов
🥬 Шпинат - лютеин для когнитивных функций  
🌰 Грецкие орехи - омега-3 для нейропластичности

---
💫 Вы не просто читаете рецепт - вы инвестируете в свое долголетие и энергию

📢 Подписывайтесь на канал! → @ppsupershef
💬 Обсуждаем в комментариях! → @ppsupershef_chat

😋 вкусно | 💪 полезно | 👨‍🍳 приготовлю | 📝 запишу себе | 📚 на рецепты

🔄 Поделитесь с друзьями! → @ppsupershef"""
        
        success = elite_channel.send_to_telegram(preview_content)
        return jsonify({"status": "success" if success else "error", "message": "Формат отправлен для предпросмотра"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# Маршруты для отправки контента
@app.route('/send-breakfast')
def send_breakfast():
    """Отправка завтрака"""
    try:
        # Определяем текущий день недели для выбора правильного типа завтрака
        kemerovo_now = datetime.now(Config.KEMEROVO_TIMEZONE)
        weekday = kemerovo_now.weekday()
        
        method_name = ContentManager.get_content_for_time("07:00", weekday)
        method = getattr(content_gen, method_name)
        content = method()
        
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error", "method": method_name})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-lunch')
def send_lunch():
    """Отправка обеда"""
    try:
        kemerovo_now = datetime.now(Config.KEMEROVO_TIMEZONE)
        weekday = kemerovo_now.weekday()
        
        method_name = ContentManager.get_content_for_time("12:00", weekday)
        method = getattr(content_gen, method_name)
        content = method()
        
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error", "method": method_name})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-science')
def send_science():
    """Отправка научного контента"""
    try:
        content = content_gen.generate_science_content()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-interval')
def send_interval():
    """Отправка контента про интервальное питание"""
    try:
        content = content_gen.generate_expert_advice()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-dinner')
def send_dinner():
    """Отправка ужина"""
    try:
        kemerovo_now = datetime.now(Config.KEMEROVO_TIMEZONE)
        weekday = kemerovo_now.weekday()
        
        method_name = ContentManager.get_content_for_time("19:00", weekday)
        method = getattr(content_gen, method_name)
        content = method()
        
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error", "method": method_name})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-advice')
def send_advice():
    """Отправка советов экспертов"""
    try:
        content = content_gen.generate_expert_advice()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-manual-content', methods=['POST'])
def send_manual_content():
    """Отправка ручного контента"""
    try:
        data = request.get_json()
        content = data.get('content', '')
        
        if not content:
            return jsonify({"status": "error", "message": "Пустое сообщение"})
        
        current_times = TimeZoneConverter.get_current_times()
        content_with_footer = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']}"
        
        success = elite_channel.send_to_telegram(content_with_footer)
        return jsonify({"status": "success" if success else "error"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    """Обработчик вебхука от Telegram"""
    try:
        data = request.get_json()
        logger.info(f"📨 Получен вебхук от Telegram: {data}")
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука: {e}")
        return jsonify({"status": "error"})

# Обработчик ошибок
@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Error: {str(error)}")
    return jsonify({"status": "error", "message": "Internal server error"}), 500

if __name__ == '__main__':
    logger.info(f"🚀 Запуск Клуба Осознанного Долголетия через Правильное Питание: @ppsupershef")
    logger.info(f"🎯 Философия: Осознанное питание как инвестиция в качество жизни")
    logger.info(f"📊 Контент-план: 45 постов в неделю")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
