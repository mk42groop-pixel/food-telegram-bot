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
    SERVER_TIMEZONE = pytz.timezone('UTC')  # Предполагаем, что сервер в UTC
    KEMEROVO_TIMEZONE = pytz.timezone('Asia/Novokuznetsk')  # Кемерово UTC+7
    TIME_DIFFERENCE_HOURS = 7  # Разница во времени: Кемерово = Сервер + 7 часов

class ContentFormatter:
    """Класс для форматирования контента с эмодзи и структурированием"""
    
    # Словари эмодзи для разных типов предложений
    EMOJI_MAPPING = {
        'start': ['🍳', '👨‍🍳', '🥘', '🍲', '🥗', '🍎', '🥑', '🍓', '🥦', '🍠'],
        'ingredient': ['🥬', '🥕', '🌶️', '🧅', '🧄', '🍅', '🥒', '🌽', '🥔', '🍆'],
        'cooking': ['🔥', '⏱️', '🥄', '🍴', '🔪', '🥣', '🍽️', '👌', '💫'],
        'health': ['💪', '🌟', '❤️', '✨', '🏆', '✅', '🌿', '🍃'],
        'tip': ['💡', '📝', '👀', '🎯', '⚠️', '🔔'],
        'benefit': ['⚡', '💥', '🔥', '🌟', '💎', '🏅'],
        'science': ['🔬', '📊', '🧪', '🔍', '🎓', '📚']
    }
    
    # Реакции для сообщений
    REACTIONS = [
        {"emoji": "😋", "text": "вкусно"},
        {"emoji": "💪", "text": "полезно"},
        {"emoji": "👨‍🍳", "text": "приготовлю"},
        {"emoji": "📝", "text": "запишу себе"},
        {"emoji": "📚", "text": "на рецепты"}
    ]
    
    # Визуальный контент
    VISUAL_CONTENT = {
        'infographics': [
            {'emoji': '📊', 'title': 'Правило тарелки', 'desc': 'Идеальное распределение продуктов'},
            {'emoji': '📈', 'title': 'Баланс БЖУ', 'desc': 'Оптимальное соотношение белков, жиров, углеводов'},
            {'emoji': '⏱️', 'title': 'Тайминг приемов пищи', 'desc': 'Когда и что лучше есть'},
            {'emoji': '🥗', 'title': 'Сезонные продукты', 'desc': 'Что есть в текущем сезоне'},
            {'emoji': '💧', 'title': 'Гидробаланс', 'desc': 'Схема потребления воды'}
        ],
        'checklists': [
            {'emoji': '🛒', 'title': 'Чек-лист продуктов', 'desc': 'Список покупок на неделю'},
            {'emoji': '🍱', 'title': 'Список для ланчбокса', 'desc': 'Что взять с собой на работу'},
            {'emoji': '📅', 'title': 'План питания на неделю', 'desc': 'Расписание приемов пищи'},
            {'emoji': '⚡', 'title': 'Экспресс-рецепты', 'desc': 'Быстрые блюда за 15 минут'},
            {'emoji': '💰', 'title': 'Бюджетное питание', 'desc': 'Экономные и полезные варианты'}
        ],
        'guides': [
            {'emoji': '🔍', 'title': 'Как читать этикетки', 'desc': 'Разбор состава продуктов'},
            {'emoji': '🏃', 'title': 'Питание при тренировках', 'desc': 'До и после физической нагрузки'},
            {'emoji': '💤', 'title': 'Питание для сна', 'desc': 'Что есть для качественного отдыха'}
        ]
    }
    
    # Система вовлечения
    ENGAGEMENT_BOOSTERS = [
        {
            'type': 'social_mention',
            'text': "📱 Отмечайте нас в сторис! Покажите свои блюда с тегом #ppsupershef",
            'hashtag': '#ppsupershef'
        },
        {
            'type': 'repost',
            'text': "🎁 Репост приветствуется! Поделитесь с друзьями - сохраняйте полезное",
            'emoji': "🎁"
        },
        {
            'type': 'user_content',
            'text': "👨‍🍳 Покажите вашу версию рецепта! Лучшие фото публикуем в канале",
            'hashtag': '#мойрецепт'
        },
        {
            'type': 'question',
            'text': "💬 Как вам рецепт? Пишите в комментариях ваши впечатления!",
            'emoji': "💬"
        },
        {
            'type': 'challenge',
            'text': "🏆 Примите кулинарный вызов! Готовите это блюдо - отмечайте нас",
            'hashtag': '#кулинарныйвызов'
        }
    ]

    # Интерактивные элементы
    INTERACTIVE_ELEMENTS = {
        'polls': [
            {
                'question': "📊 Голосуйте: Какой формат контента нравится больше?",
                'options': ['🍳 Рецепты с КБЖУ', '🔬 Научные факты', '💡 Советы экспертов', '📊 Инфографика'],
                'emoji': '📊'
            },
            {
                'question': "🥗 Какой прием пищи планируете улучшить?",
                'options': ['🍳 Завтрак', '🍲 Обед', '🍽️ Ужин', '🥨 Перекусы'],
                'emoji': '🥗'
            },
            {
                'question': "⏱️ Как часто готовите дома?",
                'options': ['📅 Каждый день', '💼 В рабочие дни', '🎉 Только выходные', '🍕 Редко готовлю'],
                'emoji': '⏱️'
            }
        ],
        'quizzes': [
            {
                'question': "🧠 Тест: Насколько вы разбираетесь в питании?",
                'options': ['💪 Профи', '📚 Любитель', '🌱 Начинающий', '❓ Только учусь'],
                'emoji': '🧠'
            }
        ]
    }

    @staticmethod
    def add_emojis_to_text(text):
        """Добавляет эмодзи в начало каждого нового предложения"""
        if not text:
            return text
            
        sentences = text.split('. ')
        formatted_sentences = []
        
        for i, sentence in enumerate(sentences):
            if sentence.strip():
                # Выбираем эмодзи в зависимости от типа предложения
                if i == 0:
                    emoji = random.choice(ContentFormatter.EMOJI_MAPPING['start'])
                elif any(word in sentence.lower() for word in ['ингредиент', 'состав', 'нужно', 'потребуется']):
                    emoji = random.choice(ContentFormatter.EMOJI_MAPPING['ingredient'])
                elif any(word in sentence.lower() for word in ['готовить', 'варить', 'жарить', 'печь', 'тушить', 'минут', 'час']):
                    emoji = random.choice(ContentFormatter.EMOJI_MAPPING['cooking'])
                elif any(word in sentence.lower() for word in ['польза', 'здоров', 'витамин', 'полезно', 'улучшает']):
                    emoji = random.choice(ContentFormatter.EMOJI_MAPPING['health'])
                elif any(word in sentence.lower() for word in ['совет', 'рекомендация', 'подсказка', 'важно']):
                    emoji = random.choice(ContentFormatter.EMOJI_MAPPING['tip'])
                elif any(word in sentence.lower() for word in ['ускоряет', 'улучшает', 'помогает', 'способствует']):
                    emoji = random.choice(ContentFormatter.EMOJI_MAPPING['benefit'])
                elif any(word in sentence.lower() for word in ['исследование', 'ученые', 'наука', 'доказано']):
                    emoji = random.choice(ContentFormatter.EMOJI_MAPPING['science'])
                else:
                    emoji = random.choice(ContentFormatter.EMOJI_MAPPING['start'])
                
                formatted_sentences.append(f"{emoji} {sentence.strip()}.")
        
        return ' '.join(formatted_sentences)
    
    @staticmethod
    def generate_kbju():
        """Генерирует случайные значения КБЖУ"""
        calories = random.randint(180, 450)
        proteins = random.randint(8, 25)
        fats = random.randint(5, 20)
        carbs = random.randint(20, 60)
        
        return {
            'calories': calories,
            'proteins': proteins,
            'fats': fats,
            'carbs': carbs
        }
    
    @staticmethod
    def format_kbju(kbju_data):
        """Форматирует КБЖУ в красивую строку"""
        return f"🍽️ КБЖУ: {kbju_data['calories']} ккал • Белки: {kbju_data['proteins']}г • Жиры: {kbju_data['fats']}г • Углеводы: {kbju_data['carbs']}г"
    
    @staticmethod
    def format_footer(channel_link="@ppsupershef", group_link="@ppsupershef_chat"):
        """Форматирует нижнюю часть сообщения с призывами к действию"""
        # Формируем строку реакций
        reactions_line = " | ".join([f"{reaction['emoji']} {reaction['text']}" for reaction in ContentFormatter.REACTIONS])
        
        footer = f"""
        
📢 <b>Подписывайтесь на канал!</b> → {channel_link}
💬 <b>Обсуждаем в комментариях!</b> → {group_link}

{reactions_line}

🔄 <b>Поделитесь с друзьями!</b> → {channel_link}
        """
        return footer

    @staticmethod
    def add_visual_content(content_type='random'):
        """Добавляет блок визуального контента"""
        if content_type == 'random':
            # Случайный выбор типа визуального контента
            content_type = random.choice(list(ContentFormatter.VISUAL_CONTENT.keys()))
        
        if content_type in ContentFormatter.VISUAL_CONTENT:
            item = random.choice(ContentFormatter.VISUAL_CONTENT[content_type])
            return f"\n\n{item['emoji']} <b>{item['title']}</b>\n{item['desc']} - сохраняйте в закладки! 📌"
        return ""

    @staticmethod
    def add_engagement_booster():
        """Добавляет случайный элемент вовлечения"""
        booster = random.choice(ContentFormatter.ENGAGEMENT_BOOSTERS)
        
        if booster['type'] == 'social_mention':
            return f"\n\n{booster['text']}"
        elif booster['type'] == 'repost':
            return f"\n\n{booster['emoji']} {booster['text']}"
        elif booster['type'] == 'user_content':
            return f"\n\n{booster['text']}"
        elif booster['type'] == 'question':
            return f"\n\n{booster['text']}"
        elif booster['type'] == 'challenge':
            return f"\n\n{booster['text']}"
        
        return ""

    @staticmethod
    def add_interactive_element(element_type='poll'):
        """Добавляет интерактивный элемент"""
        if element_type == 'poll' and ContentFormatter.INTERACTIVE_ELEMENTS['polls']:
            poll = random.choice(ContentFormatter.INTERACTIVE_ELEMENTS['polls'])
            return f"\n\n{poll['emoji']} <b>{poll['question']}</b>"
        return ""

    @staticmethod
    def format_recipe_content(title, content, include_kbju=True):
        """Форматирует полный рецепт с КБЖУ, эмодзи и футером"""
        # Генерируем КБЖУ
        if include_kbju:
            kbju_data = ContentFormatter.generate_kbju()
            kbju_line = ContentFormatter.format_kbju(kbju_data) + "\n\n"
        else:
            kbju_line = ""
        
        # Добавляем эмодзи в текст
        formatted_content = ContentFormatter.add_emojis_to_text(content)
        
        # Добавляем футер
        footer = ContentFormatter.format_footer()
        
        return f"{title}\n\n{kbju_line}{formatted_content}{footer}"

    @staticmethod
    def format_recipe_content_enhanced(title, content, include_visual=True, include_engagement=True, include_interactive=True):
        """Улучшенное форматирование с дополнительными элементами"""
        # Базовое форматирование
        formatted_content = ContentFormatter.format_recipe_content(title, content)
        
        # Добавляем визуальный контент (30% вероятность)
        if include_visual and random.random() < 0.3:
            visual_block = ContentFormatter.add_visual_content()
            formatted_content += visual_block
        
        # Добавляем элемент вовлечения (40% вероятность)
        if include_engagement and random.random() < 0.4:
            engagement_block = ContentFormatter.add_engagement_booster()
            formatted_content += engagement_block
        
        # Добавляем интерактивный элемент (25% вероятность)
        if include_interactive and random.random() < 0.25:
            interactive_block = ContentFormatter.add_interactive_element()
            formatted_content += interactive_block
        
        return formatted_content

class TimeZoneConverter:
    """Класс для конвертации времени между часовыми поясами"""
    
    @staticmethod
    def kemerovo_to_server_time(kemerovo_time_str):
        """
        Конвертирует время из Кемерово в серверное время
        kemerovo_time_str: строка времени в формате 'HH:MM' по Кемерово
        возвращает: строка времени в формате 'HH:MM' по серверному времени
        """
        try:
            # Создаем datetime объект для сегодняшней даты с временем Кемерово
            today = datetime.now(Config.KEMEROVO_TIMEZONE).date()
            kemerovo_dt = datetime.combine(today, datetime.strptime(kemerovo_time_str, '%H:%M').time())
            kemerovo_dt = Config.KEMEROVO_TIMEZONE.localize(kemerovo_dt)
            
            # Конвертируем в серверное время
            server_dt = kemerovo_dt.astimezone(Config.SERVER_TIMEZONE)
            
            return server_dt.strftime('%H:%M')
            
        except Exception as e:
            logger.error(f"❌ Ошибка конвертации времени {kemerovo_time_str}: {e}")
            return kemerovo_time_str
    
    @staticmethod
    def server_to_kemerovo_time(server_time_str):
        """
        Конвертирует время из серверного в Кемерово время
        """
        try:
            today = datetime.now(Config.SERVER_TIMEZONE).date()
            server_dt = datetime.combine(today, datetime.strptime(server_time_str, '%H:%M').time())
            server_dt = Config.SERVER_TIMEZONE.localize(server_dt)
            
            # Конвертируем в Кемерово время
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
    
    def send_scheduled_poll(self, chat_id, poll_type='content_preference'):
        """Отправка запланированного опроса"""
        formatter = ContentFormatter()
        
        if poll_type == 'content_preference':
            poll_data = random.choice(formatter.INTERACTIVE_ELEMENTS['polls'])
            return self.create_poll(chat_id, poll_data['question'], poll_data['options'])
        
        return None

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
            return self.polls_manager.send_scheduled_poll(self.channel, poll_type)
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

#инфографика #советы #питание"""
            
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
                    'maxTokens': 1000
                },
                'messages': [
                    {
                        'role': 'system',
                        'text': '''Ты эксперт по кулинарии и здоровому питанию. Создавай качественный контент.
                        
Требования к формату:
- Пиши развернутые рецепты с детальными описаниями
- Указывай точные количества ингредиентов
- Описывай пошаговый процесс приготовления
- Добавляй информацию о пользе блюда
- Используй конкретные цифры и факты
- Пиши в дружеском и motivating тоне'''
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
    
    def generate_breakfast(self):
        """Генерация контента для завтрака"""
        prompt = """Создай подробный рецепт полезного и вкусного завтрака. Включи:
1. Полный список ингредиентов с количествами
2. Пошаговый процесс приготовления
3. Польза этого блюда для здоровья
4. Советы по подаче и вариациям

Рецепт должен быть питательным и подходить для начала дня."""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_recipe_content_enhanced("🍳 ЗАВТРАК", content)
        
        # Fallback контент
        fallback_content = """Ингредиенты: овсяные хлопья - 50г, молоко - 200мл, банан - 1шт, мед - 1чл, грецкие орехи - 20г, ягоды - горсть. Залейте овсянку горячим молоком и оставьте на 5 минут. Добавьте нарезанный банан, мед и измельченные орехи. Украсьте свежими ягодами. Этот завтрак богат клетчаткой и дает энергию на весь день."""
        return self.formatter.format_recipe_content_enhanced("🍳 ЗАВТРАК", fallback_content)
    
    def generate_lunch(self):
        """Генерация контента для обеда"""
        prompt = """Придумай рецепт сбалансированного и питательного обеда. Включи:
1. Полный список ингредиентов с точными количествами
2. Детальное описание приготовления
3. Пищевую ценность блюда
4. Рекомендации по сочетанию с другими продуктами

Обед должен быть сытным и полезным."""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_recipe_content_enhanced("🍲 ОБЕД", content)
        
        fallback_content = """Ингредиенты: куриная грудка - 150г, гречка - 100г, морковь - 1шт, лук - 1шт, оливковое масло - 1стл, специи. Отварите гречку. Нарежьте курицу кубиками и обжарьте с луком и морковью. Добавьте специи и тушите 15 минут. Подавайте с гречкой. Это блюдо богато белком и сложными углеводами."""
        return self.formatter.format_recipe_content_enhanced("🍲 ОБЕД", fallback_content)
    
    def generate_science(self):
        """Генерация научного контента"""
        prompt = "Напиши интересный научный факт о питании или кулинарии с практическими рекомендациями. Используй конкретные исследования и цифры."
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            formatted_content = self.formatter.add_emojis_to_text(content)
            footer = self.formatter.format_footer()
            
            # Добавляем дополнительные элементы с вероятностью
            enhanced_content = formatted_content
            
            if random.random() < 0.3:
                enhanced_content += self.formatter.add_visual_content()
            
            if random.random() < 0.4:
                enhanced_content += self.formatter.add_engagement_booster()
            
            if random.random() < 0.25:
                enhanced_content += self.formatter.add_interactive_element()
            
            return f"🔬 НАУКА О ПИТАНИИ\n\n{enhanced_content}{footer}"
        
        fallback_content = "Исследования показывают что регулярное употребление омега-3 жирных кислот улучшает работу мозга. Добавьте в рацион рыбу и орехи. Ученые доказали что средиземноморская диета снижает риск сердечных заболеваний. Исследования подтверждают что зеленый чай ускоряет метаболизм."
        formatted_content = self.formatter.add_emojis_to_text(fallback_content)
        footer = self.formatter.format_footer()
        return f"🔬 НАУКА О ПИТАНИИ\n\n{formatted_content}{footer}"
    
    def generate_interval(self):
        """Генерация контента про интервалы"""
        prompt = "Напиши практические советы о перерывах в питании или интервальном голодании. Включи научные факты и конкретные рекомендации по времени."
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            formatted_content = self.formatter.add_emojis_to_text(content)
            footer = self.formatter.format_footer()
            
            # Добавляем дополнительные элементы с вероятностью
            enhanced_content = formatted_content
            
            if random.random() < 0.3:
                enhanced_content += self.formatter.add_visual_content()
            
            if random.random() < 0.4:
                enhanced_content += self.formatter.add_engagement_booster()
            
            if random.random() < 0.25:
                enhanced_content += self.formatter.add_interactive_element()
            
            return f"⏱️ ИНТЕРВАЛЬНОЕ ПИТАНИЕ\n\n{enhanced_content}{footer}"
        
        fallback_content = "Оптимальный перерыв между приемами пищи 3-4 часа. Интервальное голодание 16/8 улучшает метаболизм. Не пропускайте завтрак для поддержания энергии. Вечерний перерыв в питании способствует качественному сну."
        formatted_content = self.formatter.add_emojis_to_text(fallback_content)
        footer = self.formatter.format_footer()
        return f"⏱️ ИНТЕРВАЛЬНОЕ ПИТАНИЕ\n\n{formatted_content}{footer}"
    
    def generate_dinner(self):
        """Генерация контента для ужина"""
        prompt = """Предложи рецепт легкого и полезного ужина. Включи:
1. Полный список ингредиентов
2. Пошаговый процесс приготовления 
3. Польза для вечернего приема пищи
4. Советы по легкому усвоению

Ужин должен быть легким но питательным."""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_recipe_content_enhanced("🍽️ УЖИН", content)
        
        fallback_content = """Ингредиенты: творог - 150г, яйцо - 1шт, овсяные отруби - 2стл, разрыхлитель - 0.5чл, специи. Смешайте все ингредиенты. Выпекайте в формочках 25 минут при 180°C. Легкий ужин богат белком и способствует восстановлению мышц. Идеально подходит для вечернего приема пищи."""
        return self.formatter.format_recipe_content_enhanced("🍽️ УЖИН", fallback_content)
    
    def generate_expert_advice(self):
        """Генерация совета эксперта"""
        prompt = "Дай практический совет от эксперта по улучшению пищевых привычек. Включи конкретные шаги и научное обоснование."
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            formatted_content = self.formatter.add_emojis_to_text(content)
            footer = self.formatter.format_footer()
            
            # Добавляем дополнительные элементы с вероятностью
            enhanced_content = formatted_content
            
            if random.random() < 0.3:
                enhanced_content += self.formatter.add_visual_content()
            
            if random.random() < 0.4:
                enhanced_content += self.formatter.add_engagement_booster()
            
            if random.random() < 0.25:
                enhanced_content += self.formatter.add_interactive_element()
            
            return f"💡 СОВЕТ ЭКСПЕРТА\n\n{enhanced_content}{footer}"
        
        fallback_content = "Пейте воду за 30 минут до еды для улучшения пищеварения. Используйте маленькие тарелки для контроля порций. Добавляйте белок в каждый прием пищи. Готовьте еду заранее для экономии времени. Ешьте медленно и осознанно."
        formatted_content = self.formatter.add_emojis_to_text(fallback_content)
        footer = self.formatter.format_footer()
        return f"💡 СОВЕТ ЭКСПЕРТА\n\n{formatted_content}{footer}"

# Расписание публикаций
class ContentScheduler:
    def __init__(self):
        # Расписание в времени Кемерово (UTC+7)
        self.kemerovo_schedule = {
            "07:00": {"type": "breakfast", "name": "🍳 Завтрак", "generator": "generate_breakfast"},
            "12:00": {"type": "lunch", "name": "🍲 Обед", "generator": "generate_lunch"},
            "16:00": {"type": "science", "name": "🔬 Наука", "generator": "generate_science"},
            "18:00": {"type": "interval", "name": "⏱️ Интервал", "generator": "generate_interval"},
            "19:00": {"type": "dinner", "name": "🍽️ Ужин", "generator": "generate_dinner"},
            "21:00": {"type": "expert_advice", "name": "💡 Советы экспертов", "generator": "generate_expert_advice"}
        }
        
        # Дополнительное расписание для особого контента
        self.special_schedule = {
            "15:00": {"type": "visual_content", "name": "🎨 Визуальный контент", "handler": "send_visual_content"},
            "20:00": {"type": "poll", "name": "📊 Опрос", "handler": "send_poll"},
            "14:00": {"type": "engagement_post", "name": "📱 Пост вовлечения", "handler": "send_engagement_post"}
        }
        
        # Конвертируем расписания
        self.server_schedule = self._convert_schedule(self.kemerovo_schedule)
        self.server_special_schedule = self._convert_schedule(self.special_schedule)
        
        self.is_running = False
        logger.info("✅ Инициализирован улучшенный планировщик контента")

    def _convert_schedule(self, schedule):
        """Конвертирует расписание в серверное время"""
        converted = {}
        for kemerovo_time, event in schedule.items():
            server_time = TimeZoneConverter.kemerovo_to_server_time(kemerovo_time)
            converted[server_time] = event
            logger.info(f"🕒 Расписание: Кемерово {kemerovo_time} -> Сервер {server_time} - {event['name']}")
        return converted

    def get_schedule(self):
        """Возвращает расписание в обоих часовых поясах"""
        return {
            'kemerovo_schedule': self.kemerovo_schedule,
            'server_schedule': self.server_schedule,
            'special_schedule': self.special_schedule
        }
    
    def get_next_event(self):
        """Получает следующее событие с учетом часовых поясов"""
        current_times = TimeZoneConverter.get_current_times()
        current_server_time = current_times['server_time'][:5]  # Берем только HH:MM
        
        # Объединяем все расписания для поиска следующего события
        all_events = {**self.server_schedule, **self.server_special_schedule}
        
        # Ищем следующее событие в серверном времени
        times_today = [t for t in all_events.keys() if t > current_server_time]
        if times_today:
            next_server_time = min(times_today)
            next_event = all_events[next_server_time]
            
            # Конвертируем обратно в Кемерово время для отображения
            next_kemerovo_time = TimeZoneConverter.server_to_kemerovo_time(next_server_time)
            
            return next_server_time, next_kemerovo_time, next_event
        
        # Если сегодня событий больше нет, берем первое завтра
        first_server_time = min(all_events.keys())
        first_event = all_events[first_server_time]
        first_kemerovo_time = TimeZoneConverter.server_to_kemerovo_time(first_server_time)
        
        return first_server_time, first_kemerovo_time, first_event
    
    def start_scheduler(self):
        """Запуск планировщика с учетом часовых поясов"""
        if self.is_running:
            return
        
        logger.info("🚀 Запуск улучшенного планировщика контента...")
        
        # Основной контент
        for server_time, event in self.server_schedule.items():
            kemerovo_time = TimeZoneConverter.server_to_kemerovo_time(server_time)
            self._schedule_regular_content(server_time, event, kemerovo_time)
        
        # Специальный контент
        for server_time, event in self.server_special_schedule.items():
            kemerovo_time = TimeZoneConverter.server_to_kemerovo_time(server_time)
            self._schedule_special_content(server_time, event, kemerovo_time)
        
        self.is_running = True
        self._run_scheduler()

    def _schedule_regular_content(self, server_time, event, kemerovo_time):
        """Планирует регулярный контент"""
        method_name = event['generator']
        method = getattr(content_gen, method_name)
        
        def job():
            current_times = TimeZoneConverter.get_current_times()
            logger.info(f"🕒 Выполнение: {event['type']} (Кемерово: {kemerovo_time})")
            
            # Используем улучшенное форматирование
            content = method()
            if content:
                # Убрали название города из временной метки
                content_with_time = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']}"
                success = elite_channel.send_to_telegram(content_with_time)
                if success:
                    logger.info(f"✅ Успешная публикация: {event['type']}")
        
        schedule.every().day.at(server_time).do(job)
        logger.info(f"✅ Запланировано: {server_time} - {event['name']}")

    def _schedule_special_content(self, server_time, event, kemerovo_time):
        """Планирует специальный контент"""
        def job():
            current_times = TimeZoneConverter.get_current_times()
            logger.info(f"🕒 Выполнение: {event['type']} (Кемерово: {kemerovo_time})")
            
            if event['type'] == 'visual_content':
                # Случайный тип визуального контента
                content_type = random.choice(['infographics', 'checklists', 'guides'])
                elite_channel.send_visual_content(content_type)
                
            elif event['type'] == 'poll':
                elite_channel.send_poll()
                
            elif event['type'] == 'engagement_post':
                self._send_engagement_post()
        
        # Специальный контент планируем не каждый день
        if random.random() < 0.6:  # 60% вероятность
            schedule.every().day.at(server_time).do(job)
            logger.info(f"✅ Запланирован специальный контент: {server_time} - {event['name']}")

    def _send_engagement_post(self):
        """Отправляет пост для вовлечения"""
        booster = random.choice(ContentFormatter.ENGAGEMENT_BOOSTERS)
        message = f"""📱 <b>ВЗАИМОДЕЙСТВИЕ С АУДИТОРИЕЙ</b>

{booster['text']}

💫 Самые активные участники получают упоминания в канале!

🎯 Не стесняйтесь делиться мнением - ваш опыт важен для других

📢 <b>Подписывайтесь на канал!</b> → @ppsupershef
💬 <b>Обсуждаем в комментариях!</b> → @ppsupershef_chat

🔄 <b>Поделитесь с друзьями!</b> → @ppsupershef"""

        elite_channel.send_to_telegram(message)

    def _run_scheduler(self):
        """Запускает фоновый поток планировщика"""
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        
        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        logger.info("✅ Планировщик запущен с учетом часовых поясов")

# Инициализация компонентов
elite_channel = EliteChannel()
content_gen = ContentGenerator()
content_scheduler = ContentScheduler()

# Запускаем планировщик при старте
try:
    content_scheduler.start_scheduler()
    logger.info("✅ Все компоненты инициализированы")
    
    # Логируем информацию о времени
    current_times = TimeZoneConverter.get_current_times()
    logger.info(f"🌍 Текущее время сервера: {current_times['server_time']}")
    logger.info(f"🌍 Текущее время Кемерово: {current_times['kemerovo_time']}")
    
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
        
        html = f"""
        <html>
            <head>
                <title>Система управления @ppsupershef</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                    .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                    .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 5px; }}
                    .time-info {{ background: #3498db; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .schedule-container {{ display: flex; gap: 20px; margin: 20px 0; }}
                    .schedule {{ flex: 1; background: #ecf0f1; padding: 20px; border-radius: 5px; }}
                    .event {{ padding: 10px; margin: 5px 0; background: white; border-left: 4px solid #3498db; }}
                    .event-kemerovo {{ border-left-color: #e74c3c; }}
                    .event-special {{ border-left-color: #9b59b6; }}
                    .status-success {{ color: #27ae60; }}
                    .status-error {{ color: #e74c3c; }}
                    .btn {{ display: inline-block; padding: 10px 20px; margin: 5px; background: #3498db; color: white; text-decoration: none; border-radius: 5px; }}
                    .preview {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0; border-left: 4px solid #27ae60; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🍳 Система управления @ppsupershef</h1>
                        <p>ID канала: {Config.TELEGRAM_CHANNEL}</p>
                        <p class="status-{'success' if connection_info.get('status') == 'success' else 'error'}">
                            Статус: {connection_info.get('status', 'unknown')}
                        </p>
                    </div>
                    
                    <div class="time-info">
                        <h3>🌍 Информация о времени</h3>
                        <p>Текущее время сервера: <strong>{current_times['server_time']}</strong> ({current_times['server_timezone']})</p>
                        <p>Текущее время Кемерово: <strong>{current_times['kemerovo_time']}</strong> ({current_times['kemerovo_timezone']})</p>
                        <p>Разница во времени: <strong>+{Config.TIME_DIFFERENCE_HOURS} часов</strong> (Кемерово вперед)</p>
                    </div>
                    
                    <div class="preview">
                        <h3>👀 Предпросмотр формата сообщения</h3>
                        <p><strong>Новый формат включает:</strong></p>
                        <ul>
                            <li>🍽️ КБЖУ в начале рецепта</li>
                            <li>🎯 Эмодзи в начале каждого предложения</li>
                            <li>📢 Призывы к действию в конце</li>
                            <li>😋 Реакции для вовлечения</li>
                            <li>🔄 Кнопка "Поделиться с друзьями"</li>
                            <li>🎨 Визуальный контент и инфографика</li>
                            <li>📊 Интерактивные опросы</li>
                            <li>📱 Элементы вовлечения аудитории</li>
                        </ul>
                    </div>
                    
                    <div class="schedule-container">
                        <div class="schedule">
                            <h3>📅 Основное расписание (Кемерово время)</h3>
        """
        
        for time_str, event in schedule_info['kemerovo_schedule'].items():
            is_next = " (Следующая)" if time_str == next_kemerovo_time else ""
            html += f'<div class="event event-kemerovo">{time_str} - {event["name"]}{is_next}</div>'
        
        html += """
                        </div>
                        
                        <div class="schedule">
                            <h3>🎯 Специальный контент (Кемерово время)</h3>
        """
        
        for time_str, event in schedule_info['special_schedule'].items():
            html += f'<div class="event event-special">{time_str} - {event["name"]}</div>'
        
        html += f"""
                        </div>
                    </div>
                    
                    <div>
                        <h3>⚡ Быстрые действия</h3>
                        <a class="btn" href="/test-channel">Тест канала</a>
                        <a class="btn" href="/debug">Отладка</a>
                        <a class="btn" href="/health">Health Check</a>
                        <a class="btn" href="/time-info">Информация о времени</a>
                        <a class="btn" href="/preview-format" style="background: #27ae60;">Предпросмотр формата</a>
                        <a class="btn" href="/send-poll" style="background: #9b59b6;">Отправить опрос</a>
                        <a class="btn" href="/send-visual-content" style="background: #e67e22;">Визуальный контент</a>
                    </div>
                    
                    <div style="margin-top: 20px;">
                        <h3>📤 Отправка контента</h3>
        """
        
        for event in schedule_info['kemerovo_schedule'].values():
            html += f'<a class="btn" href="/send-now/{event["type"]}" style="background: #9b59b6;">{event["name"]}</a>'
        
        html += f"""
                    </div>
                    
                    <div style="margin-top: 20px; color: #7f8c8d;">
                        <p>Следующая публикация: <strong>{next_kemerovo_time} - {next_event['name']}</strong> (Кемерово)</p>
                        <p>На сервере: <strong>{next_server_time}</strong></p>
                        <p>Текущее время сервера: {current_times['server_time']}</p>
                    </div>
                </div>
            </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        logger.error(f"❌ Ошибка в главной странице: {e}")
        return f"""
        <html>
            <body>
                <h1>Система управления @ppsupershef</h1>
                <p>Ошибка: {str(e)}</p>
                <p><a href="/debug">Перейти к отладке</a></p>
            </body>
        </html>
        """

@app.route('/preview-format')
def preview_format():
    """Страница с предпросмотром нового формата"""
    try:
        # Генерируем пример контента для предпросмотра
        example_content = content_gen.generate_breakfast()
        
        html = f"""
        <html>
            <head>
                <title>Предпросмотр формата - @ppsupershef</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                    .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                    .header {{ background: #27ae60; color: white; padding: 20px; border-radius: 5px; }}
                    .preview {{ background: #f8f9fa; padding: 20px; border-radius: 5px; margin: 20px 0; border: 2px dashed #3498db; }}
                    .preview-content {{ white-space: pre-wrap; font-family: 'Courier New', monospace; line-height: 1.5; }}
                    .btn {{ display: inline-block; padding: 10px 20px; margin: 5px; background: #3498db; color: white; text-decoration: none; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>👀 Предпросмотр нового формата сообщений</h1>
                        <p>Проверьте как будут выглядеть сообщения в Telegram</p>
                    </div>
                    
                    <div>
                        <h3>📋 Особенности нового формата:</h3>
                        <ul>
                            <li><strong>🍽️ КБЖУ</strong> - в начале каждого рецепта</li>
                            <li><strong>🎯 Эмодзи</strong> - в начале каждого предложения</li>
                            <li><strong>📢 Призывы к действию</strong> - в конце сообщения</li>
                            <li><strong>😋 Реакции</strong> - для вовлечения аудитории</li>
                            <li><strong>🔄 Кнопка "Поделиться"</strong> - для вирального распространения</li>
                            <li><strong>🎨 Визуальный контент</strong> - инфографика и чек-листы</li>
                            <li><strong>📊 Интерактивные опросы</strong> - вовлечение аудитории</li>
                            <li><strong>📱 Элементы вовлечения</strong> - репосты, отметки, челленджи</li>
                        </ul>
                    </div>
                    
                    <div class="preview">
                        <h3>📝 Пример сообщения:</h3>
                        <div class="preview-content">{example_content}</div>
                    </div>
                    
                    <div>
                        <a class="btn" href="/">На главную</a>
                        <a class="btn" href="/send-now/breakfast" style="background: #27ae60;">Отправить тестовое сообщение</a>
                    </div>
                </div>
            </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        logger.error(f"❌ Ошибка в preview-format: {e}")
        return f"Ошибка: {str(e)}"

@app.route('/send-poll')
def send_poll_route():
    """Ручка для отправки тестового опроса"""
    try:
        result = elite_channel.send_poll()
        if result:
            return jsonify({
                "status": "success",
                "message": "Опрос отправлен",
                "poll_id": result.get('poll', {}).get('id')
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Не удалось отправить опрос"
            })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-visual-content')
def send_visual_content_route():
    """Ручка для отправки визуального контента"""
    try:
        content_type = request.args.get('type', 'infographics')
        success = elite_channel.send_visual_content(content_type)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "Визуальный контент отправлен" if success else "Ошибка отправки"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/time-info')
def time_info():
    """Страница с подробной информацией о времени"""
    current_times = TimeZoneConverter.get_current_times()
    schedule_info = content_scheduler.get_schedule()
    
    return jsonify({
        "current_times": current_times,
        "schedules": schedule_info,
        "time_difference_hours": Config.TIME_DIFFERENCE_HOURS,
        "next_event": content_scheduler.get_next_event()
    })

@app.route('/debug')
def debug():
    """Страница отладки"""
    connection_test = elite_channel.test_connection()
    current_times = TimeZoneConverter.get_current_times()
    
    return jsonify({
        "status": "active",
        "telegram_channel_id": Config.TELEGRAM_CHANNEL,
        "channel_username": "@ppsupershef",
        "bot_token_exists": bool(Config.TELEGRAM_BOT_TOKEN),
        "scheduler_status": "running" if content_scheduler.is_running else "stopped",
        "connection_test": connection_test,
        "time_info": current_times,
        "time_difference": f"+{Config.TIME_DIFFERENCE_HOURS} hours (Kemerovo ahead)",
        "environment": "production" if os.getenv('PRODUCTION') else "development"
    })

@app.route('/send-now/<content_type>')
def send_now(content_type):
    """Немедленная отправка контента"""
    try:
        content = None
        
        if content_type == 'breakfast':
            content = content_gen.generate_breakfast()
        elif content_type == 'lunch':
            content = content_gen.generate_lunch()
        elif content_type == 'science':
            content = content_gen.generate_science()
        elif content_type == 'dinner':
            content = content_gen.generate_dinner()
        elif content_type == 'interval':
            content = content_gen.generate_interval()
        elif content_type == 'expert_advice':
            content = content_gen.generate_expert_advice()
        else:
            return jsonify({
                "status": "error", 
                "message": f"Неизвестный тип контента: {content_type}"
            })
        
        if not content:
            return jsonify({
                "status": "error",
                "message": "Не удалось сгенерировать контент"
            })
        
        # Добавляем временную метку (без названия города)
        current_times = TimeZoneConverter.get_current_times()
        content_with_time = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']}"
        
        success = elite_channel.send_to_telegram(content_with_time)
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Контент '{content_type}' отправлен в канал",
                "channel_id": Config.TELEGRAM_CHANNEL,
                "kemerovo_time": current_times['kemerovo_time'],
                "server_time": current_times['server_time']
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Не удалось отправить '{content_type}'"
            })
            
    except Exception as e:
        logger.error(f"❌ Ошибка в send-now: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Исключение: {str(e)}"
        })

@app.route('/test-channel')
def test_channel():
    """Тестирование подключения к каналу"""
    current_times = TimeZoneConverter.get_current_times()
    test_message = f"""✅ ТЕСТ: Канал @ppsupershef работает!

🍽️ КБЖУ: 250 ккал • Белки: 15г • Жиры: 8г • Углеводы: 30г

🍳 Это тестовое сообщение для проверки работы бота.
👨‍🍳 Система автоматической публикации работает корректно.
💫 Форматирование сообщений настроено правильно.

📊 <b>Правило тарелки</b>
Идеальное распределение продуктов - сохраняйте в закладки! 📌

📱 Отмечайте нас в сторис! Покажите свои блюда с тегом #ppsupershef

📊 <b>Голосуйте: Какой формат контента нравится больше?</b>

📢 <b>Подписывайтесь на канал!</b> → @ppsupershef
💬 <b>Обсуждаем в комментариях!</b> → @ppsupershef_chat

😋 вкусно | 💪 полезно | 👨‍🍳 приготовлю | 📝 запишу себе | 📚 на рецепты

🔄 <b>Поделитесь с друзьями!</b> → @ppsupershef

🕐 Опубликовано: {current_times['kemerovo_time']}"""
    
    success = elite_channel.send_to_telegram(test_message)
    
    return jsonify({
        "status": "success" if success else "error",
        "message": "Тестовое сообщение отправлено" if success else "Ошибка отправки",
        "channel_id": Config.TELEGRAM_CHANNEL,
        "kemerovo_time": current_times['kemerovo_time'],
        "server_time": current_times['server_time'],
        "timestamp": datetime.now(Config.SERVER_TIMEZONE).isoformat()
    })

@app.route('/health')
def health_check():
    """Проверка здоровья приложения"""
    connection = elite_channel.test_connection()
    current_times = TimeZoneConverter.get_current_times()
    
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(Config.SERVER_TIMEZONE).isoformat(),
        "telegram_connection": connection,
        "scheduler_running": content_scheduler.is_running,
        "channel": "@ppsupershef",
        "time_info": current_times
    })

@app.route('/content-stats')
def content_stats():
    """Статистика по типам контента"""
    formatter = ContentFormatter()
    
    return jsonify({
        "visual_content_types": len(formatter.VISUAL_CONTENT),
        "engagement_boosters": len(formatter.ENGAGEMENT_BOOSTERS),
        "interactive_polls": len(formatter.INTERACTIVE_ELEMENTS['polls']),
        "total_variations": len(formatter.VISUAL_CONTENT) + len(formatter.ENGAGEMENT_BOOSTERS)
    })

if __name__ == '__main__':
    logger.info(f"🚀 Запуск приложения для канала: @ppsupershef")
    logger.info(f"📋 ID канала: {Config.TELEGRAM_CHANNEL}")
    
    # Логируем информацию о времени при запуске
    current_times = TimeZoneConverter.get_current_times()
    logger.info(f"🌍 Серверное время: {current_times['server_time']}")
    logger.info(f"🌍 Время Кемерово: {current_times['kemerovo_time']}")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
