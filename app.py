import os
import logging
import requests
import json
import time
import schedule
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, request, jsonify
import pytz
import random

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8459555322:AAHeddx-gWdcYXYkQHzyb9w7he9AHmZLhmA')
    TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '-1003152210862')
    TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')
    YANDEX_GPT_API_KEY = os.getenv('YANDEX_GPT_API_KEY', 'AQVN3PPgJleV36f1uQeT6F_Ph5oI5xTyFPNf18h-')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-8af2b1f4bce441f8a802c2653516237a')
    
    # Настройки часовых поясов
    SERVER_TIMEZONE = pytz.timezone('UTC')
    KEMEROVO_TIMEZONE = pytz.timezone('Asia/Novokuznetsk')
    TIME_DIFFERENCE_HOURS = 7
    
    # Приватная статистика
    ADMIN_USER_ID = os.getenv('TELEGRAM_ADMIN_ID', 'ваш_user_id_здесь')

class ContentFormatter:
    """Класс для форматирования контента с новой философией"""
    
    # Эмоциональные триггеры
    EMOTIONAL_TRIGGERS = {
        'achievement': [
            "Станьте версией себя, которой восхищаетесь",
            "Еда - ваш союзник в достижении амбиций", 
            "Инвестируйте в свое долголетие сегодня",
            "Каждая тарелка - шаг к лучшей версии себя"
        ],
        'transformation': [
            "Превратите прием пищи в инструмент роста",
            "Осознанное питание - конкурентное преимущество",
            "Ваше тело заслуживает лучшего топлива", 
            "Долголетие начинается с сегодняшнего ужина"
        ],
        'community': [
            "Присоединяйтесь к клубу тех, кто выбирает осознанность",
            "Вы не одиноки на пути к долголетию",
            "Сообщество единомышленников для вашего роста",
            "Вместе мы создаем культуру умного питания"
        ]
    }
    
    # Системный промпт для GPT
    SYSTEM_PROMPT = """Ты эксперт по осознанному долголетию и нейропитанию, нутрициолог и Шеф-повар ресторанов Мишлен. Твоя задача - создавать контент, который превращает прием пищи в инструмент для улучшения качества жизни.

ФИЛОСОФИЯ: 
"Осознанное питание как инвестиция в энергичную, долгую и продуктивную жизнь"

ТРЕБОВАНИЯ К ФОРМАТУ:
1. Начинай с эмоционального триггера о качестве жизни
2. Добавляй научное обоснование пользы
3. Давай практические рецепты с точными количествами
4. Объясняй механизм действия на организм
5. Заканчивай призывом к осознанному действию

ОСОБЕННОСТИ РЕЦЕПТОВ:
- Техники шеф-повара Мишлен, адаптированные для дома
- Научно обоснованная польза каждого ингредиента
- Баланс вкуса и функциональности
- Доступные ингредиенты с максимальной пользой

ТОН:
- Дружеский, но экспертный
- Мотивирующий, но без излишнего энтузиазма  
- Научный, но доступный
- Вдохновляющий на изменения
"""
    
    # Визуальный контент
    VISUAL_CONTENT = {
        'infographics': [
            {'emoji': '📊', 'title': 'Правило тарелки', 'desc': 'Идеальное распределение продуктов'},
            {'emoji': '📈', 'title': 'Баланс БЖУ', 'desc': 'Оптимальное соотношение белков, жиров, углеводов'},
            {'emoji': '⏱️', 'title': 'Тайминг приемов пищи', 'desc': 'Когда и что лучше есть'},
            {'emoji': '🥗', 'title': 'Сезонные продукты', 'desc': 'Что есть в текущем сезоне'},
            {'emoji': '💧', 'title': 'Гидробаланс', 'desc': 'Схема потребления воды'}
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
        
        formatted_content = f"""🎪 <b>КЛУБ ОСОЗНАННОГО ДОЛГОЛЕТИЯ</b>

{trigger}

{title}

{content}

---
💫 <b>Вы не просто читаете рецепт - вы инвестируете в свое долголетие и энергию</b>

📢 <b>Подписывайтесь на канал!</b> → @ppsupershef
💬 <b>Обсуждаем в комментариях!</b> → @ppsupershef_chat

{reactions_line}

🔄 <b>Поделитесь с друзьями!</b> → @ppsupershef"""
        
        return formatted_content

    @staticmethod
    def format_footer():
        """Форматирует нижнюю часть сообщения"""
        reactions_line = " | ".join([f"{reaction['emoji']} {reaction['text']}" for reaction in ContentFormatter.REACTIONS])
        
        return f"""
        
📢 <b>Подписывайтесь на канал!</b> → @ppsupershef
💬 <b>Обсуждаем в комментариях!</b> → @ppsupershef_chat

{reactions_line}

🔄 <b>Поделитесь с друзьями!</b> → @ppsupershef"""

class TimeZoneConverter:
    """Класс для конвертации времени между часовыми поясами"""
    
    @staticmethod
    def kemerovo_to_server_time(kemerovo_time_str):
        """Конвертирует время из Кемерово в серверное время"""
        try:
            today = datetime.now(Config.KEMEROVO_TIMEZONE).date()
            kemerovo_dt = datetime.combine(today, datetime.strptime(kemerovo_time_str, '%H:%M').time())
            kemerovo_dt = Config.KEMEROVO_TIMEZONE.localize(kemerovo_dt)
            server_dt = kemerovo_dt.astimezone(Config.SERVER_TIMEZONE)
            return server_dt.strftime('%H:%M')
        except Exception as e:
            logger.error(f"❌ Ошибка конвертации времени {kemerovo_time_str}: {e}")
            return kemerovo_time_str
    
    @staticmethod
    def server_to_kemerovo_time(server_time_str):
        """Конвертирует время из серверного в Кемерово время"""
        try:
            today = datetime.now(Config.SERVER_TIMEZONE).date()
            server_dt = datetime.combine(today, datetime.strptime(server_time_str, '%H:%M').time())
            server_dt = Config.SERVER_TIMEZONE.localize(server_dt)
            kemerovo_dt = server_dt.astimezone(Config.KEMEROVO_TIMEZONE)
            return kemerovo_dt.strftime('%H:%M')
        except Exception as e:
            logger.error(f"❌ Ошибка конвертации времени {server_time_str}: {e}")
            return server_time_str
    
    @staticmethod
    def get_current_times():
        """Возвращает текущее время в обоих часовых поясах"""
        server_now = datetime.now(Config.SERVER_TIMEZONE)
        kemerovo_now = datetime.now(Config.KEMEROVO_TIMEZONE)
        
        return {
            'server_time': server_now.strftime('%H:%M:%S'),
            'kemerovo_time': kemerovo_now.strftime('%H:%M:%S'),
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
        
        report = f"""📊 <b>ЕЖЕДНЕВНЫЙ ОТЧЕТ КАНАЛА @ppsupershef</b>

👥 Подписчиков: <b>{member_count}</b>
📅 Дата: {current_time}
📍 Время Кемерово: {TimeZoneConverter.get_current_times()['kemerovo_time']}

💫 <b>СЕГОДНЯ В КАНАЛЕ:</b>
• 🧠 Нейропитание для ясности ума
• 💪 Энергия для достижений
• 🛡️ Стратегии долголетия
• 🍰 Умные десерты для здоровья

🎯 <b>ПРИСОЕДИНЯЙТЕСЬ К КЛУБУ ОСОЗНАННОГО ДОЛГОЛЕТИЯ!</b>

#отчет #статистика #клуб"""
        
        return report

    def generate_private_report(self):
        """Генерация приватного отчета для администратора"""
        member_count = self.get_member_count()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = f"""🔐 <b>ПРИВАТНЫЙ ОТЧЕТ АДМИНИСТРАТОРА</b>

📊 <b>СТАТИСТИКА КАНАЛА</b>
👥 Подписчиков: <b>{member_count}</b>
📅 Дата: {current_time}

🌍 <b>СИСТЕМНАЯ ИНФОРМАЦИЯ:</b>
• Автопостинг: ✅ Активен
• Контент-план: ✅ Новая философия
• Вовлеченность: 📈 Растет

💡 <b>РЕКОМЕНДАЦИИ:</b>
• Продолжайте курс на осознанное долголетие
• Анализируйте реакцию на эмоциональные триггеры
• Развивайте сообщество единомышленников

⚠️ <b>ЭТОТ ОТЧЕТ ДОСТУПЕН ТОЛЬКО ВАМ</b>"""
        
        return report

    def send_private_message(self, message, user_id=None):
        """Отправка приватного сообщения администратору"""
        try:
            if not user_id:
                user_id = Config.ADMIN_USER_ID
            
            if user_id == 'ваш_user_id_здесь':
                logger.error("❌ User ID администратора не настроен")
                return False
            
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': user_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"✅ Приватное сообщение отправлено администратору")
                return True
            else:
                logger.error(f"❌ Ошибка отправки приватного сообщения: {result}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Исключение при отправке приватного сообщения: {str(e)}")
            return False

# Класс для работы с Telegram каналом
class EliteChannel:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        self.group = Config.TELEGRAM_GROUP
        self.polls_manager = TelegramPolls(self.token)
        self.formatter = ContentFormatter()
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
            message = f"""🎨 <b>{visual_item['title']}</b>

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

    # ПОНЕДЕЛЬНИК: 🧠 НЕЙРОПИТАНИЕ
    def generate_neuro_breakfast(self):
        """Генерация нейрозавтрака для ясности ума"""
        prompt = """Создай рецепт завтрака, который запускает когнитивные функции на полную мощность.

Эмоциональный триггер: "Начни день с ясностью ума, которая превратит задачи в достижения"

Научные компоненты:
- Омега-3 для нейропластичности
- Антиоксиданты для защиты мозга
- Холин для памяти и обучения
- L-тирозин для фокуса

Включи:
1. Полный список ингредиентов с точными количествами
2. Пошаговый процесс приготовления 
3. Объяснение: как каждый компонент влияет на работу мозга
4. Время приготовления (до 15 минут)
5. Советы по усилению эффекта

Используй доступные в России ингредиенты."""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА", content, "breakfast")
        
        fallback = """🥑 Омлет с авокадо и шпинатом

Ингредиенты:
• Яйца - 2 шт
• Авокадо - ½ шт  
• Шпинат - 50 г
• Грецкие орехи - 20 г
• Оливковое масло - 1 ч.л.

Приготовление:
1. Взбейте яйца с щепоткой соли
2. Обжарьте шпинат на оливковом масле 2 минуты
3. Влейте яйца, готовьте на среднем огне 5-7 минут
4. Подавайте с ломтиками авокадо и грецкими орехами

💡 Научное обоснование: Авокадо содержит омега-9 для мембран нейронов, шпинат - лютеин для когнитивных функций, грецкие орехи - омега-3 для нейропластичности."""
        return self.formatter.format_philosophy_content("🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА", fallback, "breakfast")

    def generate_neuro_dessert(self):
        """Генерация умного десерта для мозга"""
        prompt = """Создай рецепт десерта с авокадо, который улучшает когнитивные функции и поднимает настроение.

Эмоциональный триггер: "Сладкая пауза, которая делает тебя умнее"

Научные компоненты:
- Флавоноиды для улучшения памяти
- Триптофан для синтеза серотонина
- Антиоксиданты для защиты нейронов
- Магний для расслабления и фокуса

Требования:
- Использовать спелый авокадо как основу
- Сочетать с доступными в России ингредиентами
- Сохранять кремовую текстуру без сливок
- Объяснить пользу мононенасыщенных жиров
- Время приготовления до 20 минут

Научное обоснование:
- Олеиновая кислота для когнитивных функций
- Лютеин для здоровья глаз
- Глутатион для детокса"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🍫 УМНЫЙ ДЕСЕРТ ДЛЯ МОЗГА", content, "dessert")
        
        fallback = """🥑 Шоколадный мусс из авокадо

Ингредиенты:
• Авокадо - 2 спелых плода
• Какао-порошок - 3 ст.л.
• Мед - 2 ст.л.
• Банан - 1 шт
• Грецкие орехи - 30 г

Приготовление:
1. Очистите авокадо и банан
2. Взбейте в блендере до кремообразной массы
3. Добавьте какао и мед, взбейте еще раз
4. Охладите 15 минут, посыпьте грецкими орехами

💡 Научное обоснование: Авокадо содержит олеиновую кислоту для мембран нейронов, какао - флавоноиды для памяти, грецкие орехи - омега-3 для синаптической пластичности."""
        return self.formatter.format_philosophy_content("🍫 УМНЫЙ ДЕСЕРТ ДЛЯ МОЗГА", fallback, "dessert")

    # ВТОРНИК: 💪 ЭНЕРГИЯ И ТОНУС
    def generate_energy_breakfast(self):
        """Генерация энерго-завтрака для активного дня"""
        prompt = """Создай рецепт завтрака, который заряжает клеточные электростанции - митохондрии.

Эмоциональный триггер: "Проснись с энергией, которой хватит на все твои амбиции"

Ключевые компоненты:
- Коэнзим Q10 для производства энергии
- Магний для АТФ синтеза
- Витамины группы B для метаболизма
- Железо для кислородного обмена

Фокус на:
- Быстрое приготовление (до 10 минут)
- Ингредиенты, доступные в обычном магазине
- Объяснение механизма выработки энергии
- Советы по поддержанию уровня энергии"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("⚡ ЭНЕРГО-ЗАВТРАК ДЛЯ АКТИВНОГО ДНЯ", content, "breakfast")
        
        fallback = """🥣 Энергетическая овсянка с семенами

Ингредиенты:
• Овсяные хлопья - 50 г
• Миндаль - 20 г
• Семена чиа - 1 ст.л.
• Банан - 1 шт
• Корица - ½ ч.л.

Приготовление:
1. Залейте овсянку горячей водой на 5 минут
2. Добавьте нарезанный банан и семена чиа
3. Посыпьте миндалем и корицей

💡 Научное обоснование: Овсянка дает медленные углеводы для стабильной энергии, семена чиа - омега-3 для митохондрий, корица регулирует уровень сахара в крови."""
        return self.formatter.format_philosophy_content("⚡ ЭНЕРГО-ЗАВТРАК ДЛЯ АКТИВНОГО ДНЯ", fallback, "breakfast")

    # СРЕДА: 🛡️ ДОЛГОЛЕТИЕ
    def generate_longevity_breakfast(self):
        """Генерация завтрака долгожителя"""
        prompt = """Создай рецепт завтрака, который активирует гены долголетия и процессы клеточного обновления.

Эмоциональный триггер: "Каждое утро - возможность добавить здоровые годы к своей жизни"

Геропротекторы:
- Ресвератрол для активации сиртуинов
- Куркумин против воспаления
- Полифенолы для антиоксидантной защиты
- Спермидин для аутофагии

Акцент на:
- Продукты, доказано связанные с долголетием
- Простые техники приготовления
- Объяснение механизмов anti-age
- Доступные аналоги дорогих суперфудов"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🛡️ ЗАВТРАК ДОЛГОЖИТЕЛЯ", content, "breakfast")
        
        fallback = """🥣 Каша с куркумой и ягодами

Ингредиенты:
• Гречневая крупа - 50 г
• Куркума - 1 ч.л.
• Ягоды (замороженные) - 100 г
• Грецкие орехи - 20 г
• Льняное масло - 1 ч.л.

Приготовление:
1. Сварите гречневую кашу
2. Добавьте куркуму за 2 минуты до готовности
3. Подавайте с ягодами, орехами и льняным маслом

💡 Научное обоснование: Куркума содержит куркумин - мощный противовоспалительный агент, ягоды - антоцианы против окислительного стресса, льняное масло - омега-3 для клеточных мембран."""
        return self.formatter.format_philosophy_content("🛡️ ЗАВТРАК ДОЛГОЖИТЕЛЯ", fallback, "breakfast")

    # ЧЕТВЕРГ: 🍽️ ГАСТРОНОМИЧЕСКОЕ НАСЛАЖДЕНИЕ
    def generate_gastronomy_breakfast(self):
        """Генерация творческого завтрака"""
        prompt = """Создай рецепт завтрака ресторанного уровня, который доказывает: полезное может быть изысканным.

Эмоциональный триггер: "Начни день с гастрономического наслаждения, которое продлевает жизнь"

Элементы изысканности:
- Необычные сочетания вкусов
- Эстетика подачи
- Ресторанные техники
- Полезные ингредиенты премиум-класса

Фокус на:
- Простые приемы шеф-поваров для дома
- Баланс вкуса и пользы
- Время приготовления до 20 минут
- Ингредиенты, доступные в обычных магазинах"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🎨 ТВОРЧЕСКИЙ ЗАВТРАК", content, "breakfast")
        
        fallback = """🍳 Гренки с авокадо и яйцом-пашот

Ингредиенты:
• Хлеб цельнозерновой - 2 ломтика
• Авокадо - 1 шт
• Яйца - 2 шт
• Руккола - 30 г
• Семена кунжута - 1 ч.л.

Приготовление:
1. Подсушите хлеб на сухой сковороде
2. Разомните авокадо с солью
3. Приготовьте яйца-пашот (3 минуты в кипящей воде)
4. Соберите: хлеб + авокадо + руккола + яйцо

💡 Шеф-совет: Для идеального яйца-пашот добавьте в воду 1 ст.л. уксуса."""
        return self.formatter.format_philosophy_content("🎨 ТВОРЧЕСКИЙ ЗАВТРАК", fallback, "breakfast")

    # ПЯТНИЦА: 🎯 РЕЗУЛЬТАТЫ И ПЛАНЫ
    def generate_analytical_breakfast(self):
        """Генерация аналитического завтрака"""
        prompt = """Создай рецепт завтрака, который помогает анализировать прошедшую неделю и планировать следующую.

Эмоциональный триггер: "Завтрак, который превращает опыт недели в планы на будущее"

Когнитивная поддержка:
- Компоненты для ясности мышления
- Нутриенты для принятия решений
- Энергия для планирования
- Противовоспалительные для снижения стресса

Особенности:
- Связь питания и продуктивности
- Объяснение влияния на когнитивные функции
- Практические советы по планированию питания
- Подготовка к выходным без срывов"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("📊 АНАЛИТИЧЕСКИЙ ЗАВТРАК", content, "breakfast")
        
        fallback = """🥣 Творожная масса с орехами и медом

Ингредиенты:
• Творог 5% - 150 г
• Грецкие орехи - 30 г
• Мед - 1 ст.л.
• Изюм - 20 г
• Лимонный сок - 1 ч.л.

Приготовление:
1. Смешайте творог с медом и лимонным соком
2. Добавьте измельченные орехи и изюм
3. Подавайте с цельнозерновыми хлебцами

💡 Научное обоснование: Творог содержит тирозин для ясности мышления, орехи - омега-3 для когнитивных функций, мед - натуральную глюкозу для энергии мозга."""
        return self.formatter.format_philosophy_content("📊 АНАЛИТИЧЕСКИЙ ЗАВТРАК", fallback, "breakfast")

    # СУББОТА: 🛒 УМНЫЕ ПОКУПКИ + РЕЦЕПТЫ
    def generate_smart_shopping_list(self):
        """Генерация умного чек-листа покупок"""
        season = self._get_current_season()
        
        shopping_list = f"""🛒 <b>УМНЫЙ ЧЕК-ЛИСТ НА НЕДЕЛЮ</b>

Основа для осознанного долголетия + сезонные продукты ({season})

🧠 <b>ДЛЯ МОЗГА И НЕРВНОЙ СИСТЕМЫ:</b>
• Грецкие орехи - 200 г
• Авокадо - 3-4 шт
• Жирная рыба (лосось, скумбрия) - 500 г
• Яйца - 10 шт
• Темный шоколад 85% - 100 г

💪 <b>ДЛЯ ЭНЕРГИИ И ТОНУСА:</b>
• Овсяные хлопья - 500 г
• Бананы - 1 кг
• Семена чиа - 100 г
• Куриная грудка - 1 кг
• Гречневая крупа - 500 г

🛡️ <b>ДЛЯ ДОЛГОЛЕТИЯ:</b>
• Куркума - 50 г
• Имбирь - 100 г
• Чеснок - 3 головки
• Ягоды (замороженные) - 500 г
• Зеленые овощи - 1 кг

🍽️ <b>ДЛЯ ГАСТРОНОМИЧЕСКОГО НАСЛАЖДЕНИЯ:</b>
• Специи (корица, кардамон, мускат)
• Натуральный мед - 300 г
• Кокосовое молоко - 400 мл
• Оливковое масло - 500 мл

💡 <b>СОВЕТЫ ОТ ШЕФ-ПОВАРА:</b>
• Покупайте сезонные местные продукты
• Читайте составы - избегайте рафинированного сахара
• Планируйте меню на неделю вперед
• Храните орехи и семена в холодильнике

🎯 <b>ФИЛОСОФИЯ ПОКУПОК:</b>
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

    # ВОСКРЕСЕНЬЕ: 📊 АНАЛИТИКА + РЕЦЕПТЫ
    def generate_sunday_brunch(self):
        """Генерация воскресного бранча"""
        prompt = """Создай рецепт бранча, который становится ритуалом подготовки к новой неделе.

Эмоциональный триггер: "Воскресный бранч - твой стратегический ресурс для успешной недели"

Элементы ритуала:
- Блюда, требующие осознанного приготовления
- Ингредиенты для ментальной подготовки
- Сочетания для эмоционального баланса
- Техники, развивающие кулинарные навыки

Акцент на:
- Психологическую подготовку через питание
- Создание правильного настроя
- Практики осознанности в приготовлении
- Планирование питания на неделю"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🍳 ВОСКРЕСНЫЙ БРАНЧ-РИТУАЛ", content, "brunch")
        
        fallback = """🥞 Панкейки из цельнозерновой муки с ягодным соусом

Ингредиенты:
• Мука цельнозерновая - 150 г
• Яйца - 2 шт
• Кефир - 200 мл
• Разрыхлитель - 1 ч.л.
• Ягоды (замороженные) - 200 г
• Мед - 2 ст.л.

Приготовление:
1. Смешайте сухие ингредиенты
2. Добавьте яйца и кефир, замесите тесто
3. Жарьте на антипригарной сковороде по 2-3 минуты с каждой стороны
4. Для соуса разогрейте ягоды с медом

💡 Ритуал осознанности: Готовьте в тишине, концентрируясь на каждом действии. Это медитация, которая насыщает не только тело, но и душу."""
        return self.formatter.format_philosophy_content("🍳 ВОСКРЕСНЫЙ БРАНЧ-РИТУАЛ", fallback, "brunch")

    # НАУЧНЫЙ КОНТЕНТ
    def generate_science_content(self):
        """Генерация научного контента"""
        prompt = """Представь научный факт о питании и долголетии, который можно применить сегодня же.

Эмоциональный триггер: "Наука, которая меняет твое отношение к еде прямо сейчас"

Требования:
- Только доказанные исследования
- Практическое применение
- Объяснение механизма действия
- Опора на авторитетные источники

Структура:
1. Научное открытие/факт
2. Как это работает в организме
3. Как применить в питании сегодня
4. Ожидаемый эффект
5. Простые шаги для внедрения"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🔬 НАУКА ОСОЗНАННОГО ДОЛГОЛЕТИЯ", content, "science")
        
        fallback = """🏆 Научный факт: Интервальное голодание активирует аутофагию

Что это такое: Аутофагия - процесс очищения клеток от поврежденных компонентов, открытый японским ученым Ёсинори Осуми (Нобелевская премия 2016).

Как работает: При 16-часовом перерыве в питании клетки начинают "поедать" собственные поврежденные белки и органеллы, обновляясь на молекулярном уровне.

Практическое применение: Попробуйте окончить ужин в 20:00 и позавтракать в 12:00 следующего дня.

Ожидаемый эффект: Улучшение когнитивных функций, замедление старения, снижение риска возрастных заболеваний.

💡 Простые шаги: Начните с 12-часового перерыва, постепенно увеличивая до 16 часов."""
        return self.formatter.format_philosophy_content("🔬 НАУКА ОСОЗНАННОГО ДОЛГОЛЕТИЯ", fallback, "science")

    # СОВЕТЫ ЭКСПЕРТОВ
    def generate_expert_advice(self):
        """Генерация советов экспертов"""
        prompt = """Сформулируй принцип осознанного питания, который становится философией на всю жизнь.

Эмоциональный триггер: "Принцип, который превращает еду из привычки в инструмент роста"

Требования к принципу:
- Универсальность применения
- Научная обоснованность
- Простота понимания
- Глубина воздействия

Структура:
1. Формулировка принципа
2. Почему это работает (наука)
3. Как применять на практике
4. Какие результаты дает
5. Истории успеха или исследования"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("💡 ПРИНЦИПЫ УМНОГО ПИТАНИЯ", content, "advice")
        
        fallback = """🎯 Принцип: "Ешьте цвета радуги"

Формулировка: Каждый день включайте в рацион продукты всех цветов радуги - красные, оранжевые, желтые, зеленые, синие, фиолетовые.

Научное обоснование: Разные цвета овощей и фруктов указывают на наличие различных фитонутриентов:
• Красные - ликопин (против рака)
• Оранжевые - бета-каротин (зрение)
• Зеленые - лютеин (мозг)
• Синие - антоцианы (сердце)

Практическое применение: Сделайте свой обед разноцветным - салат из помидоров, моркови, перца, огурцов и капусты.

Результаты: Укрепление иммунной системы, снижение воспаления, защита от хронических заболеваний.

💡 Простой шаг: Добавьте хотя бы 3 разных цвета в каждый основной прием пищи."""
        return self.formatter.format_philosophy_content("💡 ПРИНЦИПЫ УМНОГО ПИТАНИЯ", fallback, "advice")

# Расписание публикаций
class ContentScheduler:
    def __init__(self):
        # Обновленное расписание с новой философией
        self.kemerovo_schedule = {
            # ПОНЕДЕЛЬНИК: 🧠 НЕЙРОПИТАНИЕ
            "07:00": {"type": "neuro_breakfast", "name": "🧠 Нейрозавтрак", "generator": "generate_neuro_breakfast"},
            "12:00": {"type": "focus_lunch", "name": "🎯 Обед для фокуса", "generator": "generate_energy_breakfast"},
            "16:00": {"type": "brain_science", "name": "🔬 Нейронаука", "generator": "generate_science_content"},
            "17:00": {"type": "neuro_dessert", "name": "🍫 Умный десерт", "generator": "generate_neuro_dessert"},
            "19:00": {"type": "recovery_dinner", "name": "🌙 Восстанавливающий ужин", "generator": "generate_longevity_breakfast"},
            "21:00": {"type": "evening_biohack", "name": "💫 Вечерний биохакинг", "generator": "generate_expert_advice"},

            # ВТОРНИК: 💪 ЭНЕРГИЯ И ТОНУС
            "07:00": {"type": "energy_breakfast", "name": "⚡ Энерго-завтрак", "generator": "generate_energy_breakfast"},
            "12:00": {"type": "endurance_lunch", "name": "🏃 Обед для выносливости", "generator": "generate_energy_breakfast"},
            "16:00": {"type": "energy_science", "name": "🔬 Наука энергии", "generator": "generate_science_content"},
            "17:00": {"type": "energy_dessert", "name": "🍓 Энергетический десерт", "generator": "generate_neuro_dessert"},
            "19:00": {"type": "recovery_dinner", "name": "🌙 Восстанавливающий ужин", "generator": "generate_longevity_breakfast"},
            "21:00": {"type": "energy_tips", "name": "💡 Принципы энергии", "generator": "generate_expert_advice"},

            # СРЕДА: 🛡️ ДОЛГОЛЕТИЕ
            "07:00": {"type": "longevity_breakfast", "name": "🛡️ Завтрак долгожителя", "generator": "generate_longevity_breakfast"},
            "12:00": {"type": "longevity_lunch", "name": "🌿 Обед для долголетия", "generator": "generate_longevity_breakfast"},
            "16:00": {"type": "longevity_science", "name": "🔬 Наука долголетия", "generator": "generate_science_content"},
            "17:00": {"type": "anti_age_dessert", "name": "🍇 Антиэйдж десерт", "generator": "generate_neuro_dessert"},
            "19:00": {"type": "cellular_dinner", "name": "🌙 Ужин для обновления", "generator": "generate_longevity_breakfast"},
            "21:00": {"type": "longevity_principles", "name": "💡 Принципы долголетия", "generator": "generate_expert_advice"},

            # ЧЕТВЕРГ: 🍽️ ГАСТРОНОМИЧЕСКОЕ НАСЛАЖДЕНИЕ
            "07:00": {"type": "gastronomy_breakfast", "name": "🎨 Творческий завтрак", "generator": "generate_gastronomy_breakfast"},
            "12:00": {"type": "restaurant_lunch", "name": "🍽️ Ресторанный обед", "generator": "generate_gastronomy_breakfast"},
            "16:00": {"type": "taste_science", "name": "🔬 Наука вкуса", "generator": "generate_science_content"},
            "17:00": {"type": "michelin_dessert", "name": "🎭 Шеф-десерт", "generator": "generate_neuro_dessert"},
            "19:00": {"type": "gastronomy_dinner", "name": "🌙 Гастрономический ужин", "generator": "generate_gastronomy_breakfast"},
            "21:00": {"type": "enjoyment_principles", "name": "💡 Искусство наслаждения", "generator": "generate_expert_advice"},

            # ПЯТНИЦА: 🎯 РЕЗУЛЬТАТЫ И ПЛАНЫ
            "07:00": {"type": "analytical_breakfast", "name": "📊 Аналитический завтрак", "generator": "generate_analytical_breakfast"},
            "12:00": {"type": "results_lunch", "name": "🎯 Обед для итогов", "generator": "generate_analytical_breakfast"},
            "16:00": {"type": "results_science", "name": "🔬 Наука результатов", "generator": "generate_science_content"},
            "17:00": {"type": "reflection_dessert", "name": "🍍 Десерт для осмысления", "generator": "generate_neuro_dessert"},
            "19:00": {"type": "planning_dinner", "name": "🌙 Ужин для планов", "generator": "generate_analytical_breakfast"},
            "21:00": {"type": "weekly_planning", "name": "💡 Планирование недели", "generator": "generate_expert_advice"},

            # СУББОТА: 🛒 УМНЫЕ ПОКУПКИ + РЕЦЕПТЫ
            "07:00": {"type": "weekend_breakfast", "name": "🥗 Субботний завтрак", "generator": "generate_energy_breakfast"},
            "10:00": {"type": "shopping_list", "name": "🛒 Чек-лист покупок", "generator": "generate_smart_shopping_list"},
            "12:00": {"type": "family_lunch", "name": "🍲 Семейный обед", "generator": "generate_gastronomy_breakfast"},
            "15:00": {"type": "visual_content", "name": "🎨 Визуальный контент", "handler": "send_visual_content"},
            "17:00": {"type": "weekend_dessert", "name": "🧁 Субботний десерт", "generator": "generate_neuro_dessert"},
            "19:00": {"type": "weekend_dinner", "name": "🌙 Субботний ужин", "generator": "generate_gastronomy_breakfast"},
            "21:00": {"type": "weekend_tips", "name": "💡 Советы для выходных", "generator": "generate_expert_advice"},

            # ВОСКРЕСЕНЬЕ: 📊 АНАЛИТИКА + РЕЦЕПТЫ
            "07:00": {"type": "sunday_brunch", "name": "🍳 Воскресный бранч", "generator": "generate_sunday_brunch"},
            "12:00": {"type": "sunday_lunch", "name": "🥘 Воскресный обед", "generator": "generate_gastronomy_breakfast"},
            "17:00": {"type": "sunday_dessert", "name": "🍮 Воскресный десерт", "generator": "generate_neuro_dessert"},
            "18:00": {"type": "sunday_dinner", "name": "🌙 Воскресный ужин", "generator": "generate_analytical_breakfast"},
            "21:00": {"type": "weekly_motivation", "name": "🎯 Мотивация на неделю", "generator": "generate_expert_advice"}
        }
        
        # Конвертируем расписание в серверное время
        self.server_schedule = self._convert_schedule(self.kemerovo_schedule)
        
        self.is_running = False
        logger.info("✅ Инициализирован планировщик контента с новой философией")

    def _convert_schedule(self, schedule):
        """Конвертирует расписание в серверное время"""
        converted = {}
        for kemerovo_time, event in schedule.items():
            server_time = TimeZoneConverter.kemerovo_to_server_time(kemerovo_time)
            converted[server_time] = event
            logger.info(f"🕒 Расписание: Кемерово {kemerovo_time} -> Сервер {server_time} - {event['name']}")
        return converted

    def get_schedule(self):
        """Возвращает расписание"""
        return {
            'kemerovo_schedule': self.kemerovo_schedule,
            'server_schedule': self.server_schedule
        }
    
    def get_next_event(self):
        """Получает следующее событие"""
        current_times = TimeZoneConverter.get_current_times()
        current_server_time = current_times['server_time'][:5]
        
        times_today = [t for t in self.server_schedule.keys() if t > current_server_time]
        if times_today:
            next_server_time = min(times_today)
            next_event = self.server_schedule[next_server_time]
            next_kemerovo_time = TimeZoneConverter.server_to_kemerovo_time(next_server_time)
            return next_server_time, next_kemerovo_time, next_event
        
        first_server_time = min(self.server_schedule.keys())
        first_event = self.server_schedule[first_server_time]
        first_kemerovo_time = TimeZoneConverter.server_to_kemerovo_time(first_server_time)
        return first_server_time, first_kemerovo_time, first_event
    
    def start_scheduler(self):
        """Запуск планировщика"""
        if self.is_running:
            return
        
        logger.info("🚀 Запуск планировщика контента с новой философией...")
        
        # Планируем основной контент
        for server_time, event in self.server_schedule.items():
            kemerovo_time = TimeZoneConverter.server_to_kemerovo_time(server_time)
            self._schedule_content(server_time, event, kemerovo_time)
        
        # Планируем аналитические отчеты
        self._schedule_analytics_reports()
        
        self.is_running = True
        self._run_scheduler()

    def _schedule_content(self, server_time, event, kemerovo_time):
        """Планирует контент"""
        if 'generator' in event:
            method_name = event['generator']
            method = getattr(content_gen, method_name)
        else:
            return

        def job():
            current_times = TimeZoneConverter.get_current_times()
            logger.info(f"🕒 Выполнение: {event['type']} (Кемерово: {kemerovo_time})")
            
            content = method()
            if content:
                content_with_time = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']}"
                success = elite_channel.send_to_telegram(content_with_time)
                if success:
                    logger.info(f"✅ Успешная публикация: {event['type']}")
        
        schedule.every().day.at(server_time).do(job)
        logger.info(f"✅ Запланировано: {server_time} - {event['name']}")

    def _schedule_analytics_reports(self):
        """Планирование аналитических отчетов"""
        # Публичный отчет в 09:00 по Кемерово
        public_report_time = TimeZoneConverter.kemerovo_to_server_time("09:00")
        
        def public_analytics_job():
            logger.info("📊 Генерация публичного отчета")
            report = channel_analytics.generate_public_report()
            elite_channel.send_to_telegram(report)
        
        # Приватный отчет в 09:30 по Кемерово
        private_report_time = TimeZoneConverter.kemerovo_to_server_time("09:30")
        
        def private_analytics_job():
            logger.info("🔐 Генерация приватного отчета")
            report = channel_analytics.generate_private_report()
            channel_analytics.send_private_message(report)
        
        schedule.every().day.at(public_report_time).do(public_analytics_job)
        schedule.every().day.at(private_report_time).do(private_analytics_job)
        
        logger.info(f"✅ Запланирован публичный отчет на {public_report_time}")
        logger.info(f"✅ Запланирован приватный отчет на {private_report_time}")

    def _run_scheduler(self):
        """Запускает фоновый поток планировщика"""
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        
        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        logger.info("✅ Планировщик запущен")

# Инициализация компонентов
elite_channel = EliteChannel()
content_gen = ContentGenerator()
content_scheduler = ContentScheduler()
channel_analytics = ChannelAnalytics(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHANNEL)

# Запускаем планировщик при старте
try:
    content_scheduler.start_scheduler()
    logger.info("✅ Все компоненты инициализированы")
    
    current_times = TimeZoneConverter.get_current_times()
    logger.info(f"🌍 Текущее время сервера: {current_times['server_time']}")
    logger.info(f"🌍 Время Кемерово: {current_times['kemerovo_time']}")
    
    member_count = channel_analytics.get_member_count()
    logger.info(f"📊 Начальное количество подписчиков: {member_count}")
    
    if Config.ADMIN_USER_ID and Config.ADMIN_USER_ID != 'ваш_user_id_здесь':
        startup_message = "🤖 <b>Бот @ppsupershef запущен с новой философией!</b>\n\n🎪 Теперь это Клуб Осознанного Долголетия. Приватные отчеты будут приходить вам ежедневно в 09:30."
        channel_analytics.send_private_message(startup_message)
    
except Exception as e:
    logger.error(f"❌ Ошибка инициализации: {e}")

# Маршруты Flask
@app.route('/')
def index():
    """Главная страница"""
    try:
        next_server_time, next_kemerovo_time, next_event = content_scheduler.get_next_event()
        connection_info = elite_channel.test_connection()
        current_times = TimeZoneConverter.get_current_times()
        schedule_info = content_scheduler.get_schedule()
        member_count = channel_analytics.get_member_count()
        
        admin_id_status = "✅ Настроен" if Config.ADMIN_USER_ID and Config.ADMIN_USER_ID != 'ваш_user_id_здесь' else "❌ Не настроен"
        
        html = f"""
        <html>
            <head>
                <title>Клуб Осознанного Долголетия @ppsupershef</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                    .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                    .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 5px; }}
                    .philosophy {{ background: #9b59b6; color: white; padding: 20px; border-radius: 5px; margin: 10px 0; }}
                    .stats-card {{ background: #3498db; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .private-card {{ background: #e74c3c; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .time-info {{ background: #27ae60; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .btn {{ display: inline-block; padding: 10px 20px; margin: 5px; background: #3498db; color: white; text-decoration: none; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎪 Клуб Осознанного Долголетия @ppsupershef</h1>
                        <p>ФИЛОСОФИЯ: Осознанное питание как инвестиция в энергичную, долгую и продуктивную жизнь</p>
                    </div>
                    
                    <div class="philosophy">
                        <h2>🎯 Новая концепция контента:</h2>
                        <p><strong>🧠 Нейропитание • 💪 Энергия • 🛡️ Долголетие • 🍽️ Гастрономия</strong></p>
                        <p>Каждый прием пищи - инструмент для улучшения качества жизни</p>
                    </div>
                    
                    <div class="stats-card">
                        <h2>📊 СТАТИСТИКА КАНАЛА</h2>
                        <p><strong>👥 Подписчиков: {member_count}</strong></p>
                        <p><strong>📈 Контент: 45 постов/неделя</strong></p>
                        <p><strong>🎯 Философия: Осознанное долголетие</strong></p>
                    </div>
                    
                    <div class="private-card">
                        <h2>🔐 ПРИВАТНАЯ СТАТИСТИКА</h2>
                        <p><strong>ID администратора: {admin_id_status}</strong></p>
                        <p><strong>🕒 Приватные отчеты: 09:30 (Кемерово)</strong></p>
                    </div>
                    
                    <div class="time-info">
                        <h3>🌍 ИНФОРМАЦИЯ О ВРЕМЕНИ</h3>
                        <p>Сервер: <strong>{current_times['server_time']}</strong> • Кемерово: <strong>{current_times['kemerovo_time']}</strong></p>
                        <p>Следующая публикация: <strong>{next_kemerovo_time} - {next_event['name']}</strong></p>
                    </div>
                    
                    <div>
                        <h3>⚡ БЫСТРЫЕ ДЕЙСТВИЯ</h3>
                        <a class="btn" href="/test-channel">Тест канала</a>
                        <a class="btn" href="/send-private-report" style="background: #e74c3c;">🔐 Приватный отчет</a>
                        <a class="btn" href="/send-public-report" style="background: #3498db;">📊 Публичный отчет</a>
                        <a class="btn" href="/health">Health Check</a>
                        <a class="btn" href="/debug">Отладка</a>
                    </div>
                    
                    <div style="margin-top: 20px;">
                        <h3>🎪 ОСНОВНЫЕ НАПРАВЛЕНИЯ КОНТЕНТА:</h3>
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 10px;">
                            <div style="background: #e8f6f3; padding: 10px; border-radius: 5px;">
                                <strong>🧠 Понедельник:</strong> Нейропитание
                            </div>
                            <div style="background: #fdebd0; padding: 10px; border-radius: 5px;">
                                <strong>💪 Вторник:</strong> Энергия и тонус
                            </div>
                            <div style="background: #e8daef; padding: 10px; border-radius: 5px;">
                                <strong>🛡️ Среда:</strong> Долголетие
                            </div>
                            <div style="background: #d5f5e3; padding: 10px; border-radius: 5px;">
                                <strong>🍽️ Четверг:</strong> Гастрономия
                            </div>
                            <div style="background: #fcf3cf; padding: 10px; border-radius: 5px;">
                                <strong>🎯 Пятница:</strong> Результаты
                            </div>
                            <div style="background: #d6eaf8; padding: 10px; border-radius: 5px;">
                                <strong>🛒 Суббота:</strong> Покупки + Рецепты
                            </div>
                            <div style="background: #fadbd8; padding: 10px; border-radius: 5px;">
                                <strong>📊 Воскресенье:</strong> Аналитика
                            </div>
                            <div style="background: #d1f2eb; padding: 10px; border-radius: 5px;">
                                <strong>🍰 Каждый день:</strong> Умные десерты в 17:00
                            </div>
                        </div>
                    </div>
                </div>
            </body>
        </html>
        """
        return html
        
    except Exception as e:
        logger.error(f"❌ Ошибка в главной странице: {e}")
        return f"Ошибка: {str(e)}"

@app.route('/send-private-report')
def send_private_report():
    """Отправка приватного отчета"""
    try:
        report = channel_analytics.generate_private_report()
        success = channel_analytics.send_private_message(report)
        
        if success:
            return jsonify({"status": "success", "message": "Приватный отчет отправлен"})
        else:
            return jsonify({"status": "error", "message": "Ошибка отправки"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

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
    test_message = f"""🎪 <b>ТЕСТ: Клуб Осознанного Долголетия @ppsupershef работает!</b>

Новая философия контента активирована:

🧠 <b>Нейропитание</b> - пища для ясности ума
💪 <b>Энергия</b> - топливо для достижений  
🛡️ <b>Долголетие</b> - стратегии здоровой жизни
🍽️ <b>Гастрономия</b> - наслаждение с пользой

🤖 <b>Автопостинг:</b> ✅ Активен
🎯 <b>Контент-план:</b> 45 постов/неделя
💫 <b>Философия:</b> Осознанное питание как инвестиция в качество жизни

Присоединяйтесь к клубу тех, кто выбирает осознанность!

🕐 Опубликовано: {current_times['kemerovo_time']}"""
    
    success = elite_channel.send_to_telegram(test_message)
    return jsonify({"status": "success" if success else "error"})

@app.route('/health')
def health_check():
    """Проверка здоровья"""
    connection = elite_channel.test_connection()
    current_times = TimeZoneConverter.get_current_times()
    member_count = channel_analytics.get_member_count()
    
    return jsonify({
        "status": "healthy",
        "philosophy": "🎪 Клуб Осознанного Долголетия",
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
        "philosophy": "Осознанное долголетие",
        "content_plan": "45 постов/неделя",
        "member_count": member_count,
        "scheduler_status": "running" if content_scheduler.is_running else "stopped",
        "time_info": current_times
    })

if __name__ == '__main__':
    logger.info(f"🚀 Запуск Клуба Осознанного Долголетия: @ppsupershef")
    logger.info(f"🎯 Философия: Осознанное питание как инвестиция в качество жизни")
    logger.info(f"📊 Контент-план: 45 постов в неделю")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
