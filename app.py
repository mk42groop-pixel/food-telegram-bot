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
        # Полное расписание на всю неделю в времени Кемерово (UTC+7)
        self.kemerovo_schedule = {
            'monday': {
                "07:00": {"type": "neuro_breakfast", "name": "🧠 Нейрозавтрак для ясности ума", "generator": "generate_neuro_breakfast"},
                "12:00": {"type": "focus_lunch", "name": "🎯 Обед для фокуса и концентрации", "generator": "generate_energy_breakfast"},
                "16:00": {"type": "brain_science", "name": "🔬 Научный факт о мозге и питании", "generator": "generate_science_content"},
                "17:00": {"type": "neuro_dessert", "name": "🍫 Умный десерт для когнитивных функций", "generator": "generate_neuro_dessert"},
                "19:00": {"type": "recovery_dinner", "name": "🌙 Восстанавливающий ужин для нервной системы", "generator": "generate_longevity_breakfast"},
                "21:00": {"type": "evening_biohack", "name": "💫 Вечерний биохакинг для мозга", "generator": "generate_expert_advice"}
            },
            'tuesday': {
                "07:00": {"type": "energy_breakfast", "name": "⚡ Энерго-завтрак для активного дня", "generator": "generate_energy_breakfast"},
                "12:00": {"type": "endurance_lunch", "name": "🏃 Обед для выносливости и энергии", "generator": "generate_energy_breakfast"},
                "16:00": {"type": "energy_science", "name": "🔬 Наука энергии и метаболизма", "generator": "generate_science_content"},
                "17:00": {"type": "energy_dessert", "name": "🍓 Энергетический десерт", "generator": "generate_neuro_dessert"},
                "19:00": {"type": "recovery_dinner", "name": "🌙 Восстанавливающий ужин для мышц", "generator": "generate_longevity_breakfast"},
                "21:00": {"type": "energy_tips", "name": "💡 Принципы поддержания энергии", "generator": "generate_expert_advice"}
            },
            'wednesday': {
                "07:00": {"type": "longevity_breakfast", "name": "🛡️ Завтрак долгожителя", "generator": "generate_longevity_breakfast"},
                "12:00": {"type": "longevity_lunch", "name": "🌿 Обед для долголетия", "generator": "generate_longevity_breakfast"},
                "16:00": {"type": "longevity_science", "name": "🔬 Наука anti-age питания", "generator": "generate_science_content"},
                "17:00": {"type": "anti_age_dessert", "name": "🍇 Антиэйдж десерт", "generator": "generate_neuro_dessert"},
                "19:00": {"type": "cellular_dinner", "name": "🌙 Ужин для клеточного обновления", "generator": "generate_longevity_breakfast"},
                "21:00": {"type": "longevity_principles", "name": "💡 Принципы долголетия", "generator": "generate_expert_advice"}
            },
            'thursday': {
                "07:00": {"type": "gastronomy_breakfast", "name": "🎨 Творческий завтрак ресторанного уровня", "generator": "generate_gastronomy_breakfast"},
                "12:00": {"type": "restaurant_lunch", "name": "🍽️ Ресторанный обед с пользой", "generator": "generate_gastronomy_breakfast"},
                "16:00": {"type": "taste_science", "name": "🔬 Наука вкуса и наслаждения", "generator": "generate_science_content"},
                "17:00": {"type": "michelin_dessert", "name": "🎭 Шеф-десерт от Мишлен", "generator": "generate_neuro_dessert"},
                "19:00": {"type": "gastronomy_dinner", "name": "🌙 Гастрономический ужин", "generator": "generate_gastronomy_breakfast"},
                "21:00": {"type": "enjoyment_principles", "name": "💡 Искусство осознанного наслаждения", "generator": "generate_expert_advice"}
            },
            'friday': {
                "07:00": {"type": "analytical_breakfast", "name": "📊 Аналитический завтрак для планирования", "generator": "generate_analytical_breakfast"},
                "12:00": {"type": "results_lunch", "name": "🎯 Обед для подведения итогов", "generator": "generate_analytical_breakfast"},
                "16:00": {"type": "results_science", "name": "🔬 Наука продуктивности и питания", "generator": "generate_science_content"},
                "17:00": {"type": "reflection_dessert", "name": "🍍 Десерт для осмысления недели", "generator": "generate_neuro_dessert"},
                "19:00": {"type": "planning_dinner", "name": "🌙 Ужин для планов на выходные", "generator": "generate_analytical_breakfast"},
                "21:00": {"type": "weekly_planning", "name": "💡 Планирование питания на следующую неделю", "generator": "generate_expert_advice"}
            },
            'saturday': {
                "07:00": {"type": "weekend_breakfast", "name": "🥗 Субботний завтрак для семьи", "generator": "generate_energy_breakfast"},
                "10:00": {"type": "shopping_list", "name": "🛒 Умный чек-лист покупок на неделю", "generator": "generate_smart_shopping_list"},
                "12:00": {"type": "family_lunch", "name": "🍲 Семейный обед", "generator": "generate_gastronomy_breakfast"},
                "15:00": {"type": "visual_content", "name": "🎨 Визуальный контент (инфографика)", "handler": "send_visual_content"},
                "17:00": {"type": "weekend_dessert", "name": "🧁 Субботний десерт", "generator": "generate_neuro_dessert"},
                "19:00": {"type": "weekend_dinner", "name": "🌙 Субботний ужин", "generator": "generate_gastronomy_breakfast"},
                "21:00": {"type": "weekend_tips", "name": "💡 Советы для выходных", "generator": "generate_expert_advice"}
            },
            'sunday': {
                "07:00": {"type": "sunday_brunch", "name": "🍳 Воскресный бранч-ритуал", "generator": "generate_sunday_brunch"},
                "12:00": {"type": "sunday_lunch", "name": "🥘 Воскресный обед", "generator": "generate_gastronomy_breakfast"},
                "17:00": {"type": "sunday_dessert", "name": "🍮 Воскресный десерт", "generator": "generate_neuro_dessert"},
                "18:00": {"type": "sunday_dinner", "name": "🌙 Воскресный ужин для подготовки к неделе", "generator": "generate_analytical_breakfast"},
                "21:00": {"type": "weekly_motivation", "name": "🎯 Мотивация и настрой на новую неделю", "generator": "generate_expert_advice"}
            }
        }
        
        # Конвертируем расписание в серверное время
        self.server_schedule = self._convert_schedule_to_server()
        
        self.is_running = False
        logger.info("✅ Инициализирован планировщик контента с новой философией")

    def _convert_schedule_to_server(self):
        """Конвертирует все расписание в серверное время"""
        server_schedule = {}
        for day, day_schedule in self.kemerovo_schedule.items():
            server_schedule[day] = {}
            for kemerovo_time, event in day_schedule.items():
                server_time = TimeZoneConverter.kemerovo_to_server_time(kemerovo_time)
                server_schedule[day][server_time] = event
                logger.info(f"🕒 Расписание: {day} - Кемерово {kemerovo_time} -> Сервер {server_time} - {event['name']}")
        return server_schedule

    def get_schedule(self):
        """Возвращает расписание"""
        return {
            'kemerovo_schedule': self.kemerovo_schedule,
            'server_schedule': self.server_schedule
        }
    
    def get_next_event(self):
        """Получает следующее событие с учетом текущего дня недели"""
        try:
            current_times = TimeZoneConverter.get_current_times()
            current_kemerovo_time = current_times['kemerovo_time'][:5]
            
            # Получаем текущий день недели (0-6, где 0-понедельник)
            current_weekday = datetime.now(Config.KEMEROVO_TIMEZONE).weekday()
            days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            current_day = days[current_weekday]
            
            # Получаем расписание на текущий день
            today_schedule = self.kemerovo_schedule.get(current_day, {})
            
            # Ищем следующее событие сегодня
            times_today = [t for t in today_schedule.keys() if t > current_kemerovo_time]
            
            if times_today:
                # Есть посты сегодня
                next_kemerovo_time = min(times_today)
                next_event = today_schedule[next_kemerovo_time]
                next_server_time = TimeZoneConverter.kemerovo_to_server_time(next_kemerovo_time)
                return next_server_time, next_kemerovo_time, next_event
            else:
                # Постов сегодня больше нет, берем первый пост завтра
                next_weekday = (current_weekday + 1) % 7
                next_day = days[next_weekday]
                next_day_schedule = self.kemerovo_schedule.get(next_day, {})
                
                if next_day_schedule:
                    next_kemerovo_time = min(next_day_schedule.keys())
                    next_event = next_day_schedule[next_kemerovo_time]
                    next_server_time = TimeZoneConverter.kemerovo_to_server_time(next_kemerovo_time)
                    return next_server_time, next_kemerovo_time, next_event
            
            # Если ничего не найдено, возвращаем заглушку
            return "17:00", "17:00", {"name": "Следующий пост", "type": "unknown"}
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения следующего события: {e}")
            return "17:00", "17:00", {"name": "Следующий пост", "type": "unknown"}
    
    def start_scheduler(self):
        """Запуск планировщика"""
        if self.is_running:
            return
        
        logger.info("🚀 Запуск планировщика контента с новой философией...")
        
        # Планируем основной контент для каждого дня
        for day, day_schedule in self.server_schedule.items():
            for server_time, event in day_schedule.items():
                if 'generator' in event:
                    self._schedule_daily_content(day, server_time, event)
        
        # Планируем ежедневный отчет
        self._schedule_analytics_reports()
        
        self.is_running = True
        self._run_scheduler()

    def _schedule_daily_content(self, day, server_time, event):
        """Планирует контент для конкретного дня"""
        def job():
            current_times = TimeZoneConverter.get_current_times()
            logger.info(f"🕒 Выполнение: {event['name']}")
            
            if 'generator' in event:
                method_name = event['generator']
                method = getattr(content_gen, method_name)
                content = method()
            else:
                content = None
            
            if content:
                content_with_time = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']}"
                success = elite_channel.send_to_telegram(content_with_time)
                if success:
                    logger.info(f"✅ Успешная публикация: {event['name']}")
        
        # Планируем задачу на конкретный день и время
        getattr(schedule.every(), day).at(server_time).do(job)
        logger.info(f"✅ Запланировано: {day} {server_time} - {event['name']}")

    def _schedule_analytics_reports(self):
        """Планирование аналитических отчетов"""
        # Публичный отчет в 09:00 по Кемерово каждый день
        public_report_time = TimeZoneConverter.kemerovo_to_server_time("09:00")
        
        def public_analytics_job():
            logger.info("📊 Генерация публичного отчета")
            report = channel_analytics.generate_public_report()
            elite_channel.send_to_telegram(report)
        
        schedule.every().day.at(public_report_time).do(public_analytics_job)
        logger.info(f"✅ Запланирован публичный отчет на {public_report_time}")

    def _run_scheduler(self):
        """Запускает фоновый поток планировщика"""
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        
        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        logger.info("✅ Планировщик запущен")

    def _get_day_theme(self, weekday):
        """Возвращает тему дня недели"""
        themes = {
            0: "🧠 Нейропитание - фокус на мозг и когнитивные функции",
            1: "💪 Энергия и тонус - заряд энергии для достижений", 
            2: "🛡️ Долголетие - стратегии здоровой долгой жизни",
            3: "🍽️ Гастрономическое наслаждение - изысканность с пользой",
            4: "🎯 Результаты и планы - аналитика и планирование",
            5: "🛒 Умные покупки + рецепты - подготовка к неделе",
            6: "📊 Аналитика + ритуалы - настрой на новую неделю"
        }
        return themes.get(weekday, "Осознанное питание")

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
                    .content-section {{ background: white; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                    .quick-actions {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 20px 0; }}
                    .content-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 20px 0; }}
                    .form-group {{ margin: 10px 0; }}
                    input, textarea, select {{ width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 5px; }}
                    .day-info {{ background: #9b59b6; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎪 Система управления @ppsupershef</h1>
                        <p>ФИЛОСОФИЯ: Осознанное питание как инвестиция в энергичную, долгую и продуктивную жизнь</p>
                    </div>
                    
                    <div class="day-info">
                        <h2>📅 Сегодня: {current_day_name}</h2>
                        <p>Тема дня: {content_scheduler._get_day_theme(current_weekday)}</p>
                    </div>
                    
                    <div class="quick-actions">
                        <button class="btn" onclick="testChannel()">📊 Статистика</button>
                        <button class="btn" onclick="testConnection()">Тест канала</button>
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
                    
                    <div class="stats-card">
                        <h2>📊 СТАТИСТИКА КАНАЛА</h2>
                        <p><strong>👥 Подписчиков: {member_count}</strong></p>
                        <p><strong>📈 Контент: 45 постов/неделя</strong></p>
                        <p><strong>🎯 Философия: Осознанное долголетие</strong></p>
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
        preview_content = """🎪 <b>КЛУБ ОСОЗНАННОГО ДОЛГОЛЕТИЯ</b>

Станьте версией себя, которой восхищаетесь

🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА

🥑 Омлет с авокадо и шпинатом

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

💡 Научное обоснование: Авокадо содержит омега-9 для мембран нейронов, шпинат - лютеин для когнитивных функций, грецкие орехи - омега-3 для нейропластичности.

---
💫 <b>Вы не просто читаете рецепт - вы инвестируете в свое долголетие и энергию</b>

📢 <b>Подписывайтесь на канал!</b> → @ppsupershef
💬 <b>Обсуждаем в комментариях!</b> → @ppsupershef_chat

😋 вкусно | 💪 полезно | 👨‍🍳 приготовлю | 📝 запишу себе | 📚 на рецепты

🔄 <b>Поделитесь с друзьями!</b> → @ppsupershef"""
        
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
        current_weekday = datetime.now(Config.KEMEROVO_TIMEZONE).weekday()
        breakfast_types = [
            "generate_neuro_breakfast", "generate_energy_breakfast", 
            "generate_longevity_breakfast", "generate_gastronomy_breakfast",
            "generate_analytical_breakfast", "generate_energy_breakfast",
            "generate_sunday_brunch"
        ]
        method_name = breakfast_types[current_weekday]
        method = getattr(content_gen, method_name)
        content = method()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-lunch')
def send_lunch():
    """Отправка обеда"""
    try:
        content = content_gen.generate_energy_breakfast()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
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
        content = content_gen.generate_longevity_breakfast()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
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
    logger.info(f"🚀 Запуск Клуба Осознанного Долголетия: @ppsupershef")
    logger.info(f"🎯 Философия: Осознанное питание как инвестиция в качество жизни")
    logger.info(f"📊 Контент-план: 45 постов в неделю")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
