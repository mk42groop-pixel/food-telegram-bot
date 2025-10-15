import os
import requests
import schedule
import time
import random
from datetime import datetime, timedelta, timezone
from threading import Thread
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)

# Ключи из вашего проекта
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8459555322:AAHeddx-gWdcYXYkQHzyb9w7he9AHmZLhmA')
TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '@ppsupershef')  # ПРАВИЛЬНОЕ НАЗВАНИЕ
YANDEX_API_KEY = os.getenv('YANDEX_GPT_API_KEY', 'AQVN3PPgJleV36f1uQeT6F_Ph5oI5xTyFPNf18h-')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-8af2b1f4bce441f8a802c2653516237a')

class AIContentGenerator:
    def __init__(self):
        self.yandex_gpt = YandexGPT()
        self.deepseek_gpt = DeepSeekGPT()
        
    def generate_content(self, prompt, content_type="recipe"):
        """Умная генерация контента с использованием доступных AI"""
        # Сначала пробуем DeepSeek (более современный)
        content = self.deepseek_gpt.generate_content(prompt, content_type)
        if content:
            return f"🤖 {content}\n\n#AI_рецепт"
        
        # Если DeepSeek не сработал, пробуем Yandex GPT
        content = self.yandex_gpt.generate_text(prompt)
        if content:
            return f"🤖 {content}\n\n#AI_рецепт"
        
        return None

class YandexGPT:
    def __init__(self):
        self.api_key = YANDEX_API_KEY
        self.folder_id = YANDEX_FOLDER_ID
        self.base_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        self.is_active = bool(self.api_key and self.folder_id and self.api_key != 'AQVN3PPgJleV36f1uQeT6F_Ph5oI5xTyFPNf18h-')
        print(f"🤖 Yandex GPT: {'✅ Активен' if self.is_active else '❌ Не настроен'}")
        
    def generate_text(self, prompt, temperature=0.7):
        """Генерация текста через Yandex GPT"""
        if not self.is_active:
            return None
            
        headers = {
            'Authorization': f'Api-Key {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'modelUri': f'gpt://{self.folder_id}/yandexgpt-lite',
            'completionOptions': {
                'stream': False,
                'temperature': temperature,
                'maxTokens': 2000
            },
            'messages': [
                {
                    'role': 'user',
                    'text': prompt
                }
            ]
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=data, timeout=20)
            if response.status_code == 200:
                result = response.json()
                return result['result']['alternatives'][0]['message']['text']
            else:
                print(f"❌ Ошибка Yandex GPT API: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Ошибка соединения с Yandex GPT: {e}")
            return None

class DeepSeekGPT:
    def __init__(self):
        self.api_key = DEEPSEEK_API_KEY
        self.base_url = "https://api.deepseek.com/v1/chat/completions"
        self.is_active = bool(self.api_key and self.api_key != 'sk-8af2b1f4bce441f8a802c2653516237a')
        print(f"🤖 DeepSeek GPT: {'✅ Активен' if self.is_active else '❌ Не настроен'}")
        
    def generate_content(self, prompt, content_type="recipe"):
        """Генерация контента через DeepSeek"""
        if not self.is_active:
            return None
            
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        # Улучшенные промпты для разных типов контента
        system_prompts = {
            "recipe": """Ты шеф-повар ресторанов Мишлен и нутрициолог с 40-летним стажем. 
Создавай рецепты, которые одновременно вкусные и полезные. 
Формат:
🍳 НАЗВАНИЕ БЛЮДА

🥗 ИНГРЕДИЕНТЫ:
• Список

👨‍🍳 ПРИГОТОВЛЕНИЕ:
1. Шаги

📊 ПИТАТЕЛЬНАЯ ЦЕННОСТЬ:
Калории, БЖУ, польза

🎯 СОВЕТ ЭКСПЕРТА:""",
            
            "science": """Ты нутрициолог с 40-летним стажем. Объясняй сложные научные концепции простым языком.
Формат:
🔬 НАУЧНЫЙ ФАКТ

📚 ОБЪЯСНЕНИЕ:
Простыми словами

💡 ПРАКТИЧЕСКОЕ ПРИМЕНЕНИЕ:
Конкретные действия""",
            
            "advice": """Ты команда экспертов: нутрициолог с 40-летним стажем, шеф-повар Мишлен и фитнес-тренер.
Давай комплексные советы по питанию и здоровому образу жизни."""
        }
        
        data = {
            'model': 'deepseek-chat',
            'messages': [
                {
                    'role': 'system',
                    'content': system_prompts.get(content_type, system_prompts["recipe"])
                },
                {
                    'role': 'user', 
                    'content': prompt
                }
            ],
            'temperature': 0.7,
            'max_tokens': 2000
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=data, timeout=25)
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                print(f"❌ Ошибка DeepSeek API: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Ошибка соединения с DeepSeek: {e}")
            return None

class EliteContentManager:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.channel = TELEGRAM_CHANNEL  # @ppsupershef
        self.timezone_offset = 7
        self.ai_generator = AIContentGenerator()
        self.content_strategy = self._initialize_content_strategy()
        
    def get_kemerovo_time(self):
        """Получаем текущее время в Кемерово (UTC+7)"""
        utc_time = datetime.now(timezone.utc)
        kemerovo_time = utc_time + timedelta(hours=self.timezone_offset)
        return kemerovo_time
    
    def _initialize_content_strategy(self):
        """Элитная стратегия контента по методологии 'Эликсир Жизни'"""
        return {
            "weekly_themes": {
                0: "🧬 НАУЧНЫЙ ПОНЕДЕЛЬНИК: Биохимия питания",
                1: "👨‍🍳 TECH CHECK: Техники шефа", 
                2: "💬 СРЕДА ОТВЕТОВ: Команда экспертов",
                3: "🍽️ РЕЦЕПТ НЕДЕЛИ: Шедевр от Мишлен",
                4: "📊 ТРЕНДОВАЯ ПЯТНИЦА: Анализ тенденций",
                5: "⚡ БЫСТРО & ЗДОРОВО: Простые решения",
                6: "🎯 ВОСКРЕСНЫЙ ДАЙДЖЕСТ: Итоги и мотивация"
            },
            "content_pillars": {
                "science": "🧬 Научный подход к питанию",
                "taste": "👨‍🍳 Гастрономические шедевры", 
                "results": "💪 Практические результаты"
            },
            "expert_voices": {
                "nutritionist": "🧬 Нутрициолог с 40-летним стажем",
                "chef": "👨‍🍳 Шеф-повар Мишлен",
                "trainer": "💪 Фитнес-тренер мирового уровня"
            }
        }
    
    def generate_elite_content(self, content_type, weekday=None):
        """Генерация элитного контента по методологии"""
        if weekday is None:
            weekday = self.get_kemerovo_time().weekday()
            
        theme = self.content_strategy["weekly_themes"][weekday]
        
        content_generators = {
            'breakfast': self._generate_breakfast_content,
            'lunch': self._generate_lunch_content,
            'dinner': self._generate_dinner_content,
            'snack': self._generate_snack_content,
            'science': self._generate_science_content,
            'visual': self._generate_visual_content,
            'interactive': self._generate_interactive_content,
            'expert_advice': self._generate_expert_advice
        }
        
        content = content_generators[content_type](weekday, theme)
        
        # Добавляем экспертный контекст
        content += self._add_expert_context(content_type)
        
        # Добавляем призыв к действию
        content += self._get_elite_call_to_action()
        
        return content
    
    def _generate_breakfast_content(self, weekday, theme):
        """Элитный завтрак с научным обоснованием"""
        prompt = f"""
        Создай рецепт завтрака для темы: {theme}
        
        Требования:
        - Соответствие циркадным ритмам
        - Оптимальный баланс БЖУ для утра
        - Научное обоснование пользы
        - Простота приготовления
        - Ингредиенты доступные в России
        
        Включи раздел "🧬 НАУЧНОЕ ОБОСНОВАНИЕ" от нутрициолога
        """
        
        ai_content = self.ai_generator.generate_content(prompt, "recipe")
        if ai_content:
            return f"🌅 ЗАВТРАК ПРЕМИУМ-КЛАССА\n\n{theme}\n\n{ai_content}"
        
        return self._get_static_breakfast(weekday)
    
    def _generate_lunch_content(self, weekday, theme):
        """Элитный обед с фокусом на продуктивность"""
        prompt = f"""
        Создай рецепт обеда для темы: {theme}
        
        Особые требования:
        - Оптимизирован для рабочей продуктивности
        - Не вызывает сонливость
        - Содержит компоненты для мозга
        - Подходит для ланчбокса
        
        Добавь совет от шефа по приготовлению
        """
        
        ai_content = self.ai_generator.generate_content(prompt, "recipe")
        if ai_content:
            return f"🍽️ ОБЕД ДЛЯ ПРОДУКТИВНОСТИ\n\n{theme}\n\n{ai_content}"
        
        return self._get_static_lunch(weekday)
    
    def _generate_dinner_content(self, weekday, theme):
        """Элитный ужин для восстановления"""
        prompt = f"""
        Создай рецепт ужина для темы: {theme}
        
        Критерии:
        - Способствует качественному сну
        - Восстанавливает организм
        - Легкий но питательный
        - Подходит для вечернего метаболизма
        
        Включи рекомендации по времени приема пищи
        """
        
        ai_content = self.ai_generator.generate_content(prompt, "recipe")
        if ai_content:
            return f"🌙 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ\n\n{theme}\n\n{ai_content}"
        
        return self._get_static_dinner(weekday)
    
    def _generate_science_content(self, weekday, theme):
        """Научный контент от нутрициолога"""
        science_topics = [
            "Циркадные ритмы и питание: как время приема пищи влияет на метаболизм",
            "Микробиом кишечника: как бактерии управляют вашим здоровьем",
            "Гормоны голода и насыщения: лептин и грелин",
            "Эпигенетика питания: как еда влияет на экспрессию генов",
            "Воспалительные процессы в организме и противовоспалительные продукты",
            "Окислительный стресс и антиоксиданты",
            "Инсулинорезистентность и метаболическое здоровье"
        ]
        
        prompt = f"""
        Раскрой тему: {science_topics[weekday]}
        
        Формат:
        🔬 НАУЧНЫЙ ФАКТ
        📚 ПРОСТОЕ ОБЪЯСНЕНИЕ
        💡 ПРАКТИЧЕСКОЕ ПРИМЕНЕНИЕ
        🎯 РЕКОМЕНДАЦИИ ЭКСПЕРТА
        
        Используй язык, понятный неспециалистам
        """
        
        ai_content = self.ai_generator.generate_content(prompt, "science")
        if ai_content:
            return f"🧬 ЭКСПЕРТНОЕ ЗНАНИЕ\n\n{theme}\n\n{ai_content}"
        
        return self._get_static_science(weekday)
    
    def _generate_visual_content(self, weekday, theme):
        """Премиальный визуальный контент"""
        infographics = [
            {
                'title': '📊 ПРАВИЛО ТАРЕЛКИ ОТ МИШЛЕН',
                'content': '''• ½ Тарелки - ОВОЩИ (клетчатка, витамины)
• ¼ Тарелки - БЕЛКИ (рыба, курица, тофу)  
• ¼ Тарелки - СЛОЖНЫЕ УГЛЕВОДЫ (киноа, гречка)
• + Полезные жиры (авокадо, оливковое масло)

🎯 Шеф-совет: "Баланс текстур и вкусов"''',
                'hashtags': '#ПравилоТарелки #Мишлен #Баланс'
            },
            {
                'title': '⏱️ ЦИРКАДНОЕ ПИТАНИЕ',
                'content': '''🕗 7-9 УТРА: Белково-углеводный завтрак
🕛 12-14 ДНЯ: Сбалансированный обед
🕐 16-17 ВЕЧЕРА: Легкий перекус
🕢 18-20 ВЕЧЕРА: Легкий ужин

🧬 Научный факт: Соблюдение времени приемов пищи ускоряет метаболизм на 15%''',
                'hashtags': '#ЦиркадноеПитание #Метаболизм #Наука'
            }
        ]
        
        visual = infographics[weekday % len(infographics)]
        return f"🎨 ПРЕМИУМ ИНФОГРАФИКА\n\n{visual['title']}\n\n{visual['content']}\n\n{visual['hashtags']}"
    
    def _generate_interactive_content(self, weekday, theme):
        """Интерактивный контент премиум-класса"""
        interactions = [
            "💬 **ОПРОС ЭКСПЕРТОВ**: Какой аспект питания для вас самый сложный?\n\n• 🕒 Тайминг приемов пищи\n• 🛒 Выбор качественных продуктов\n• 🍳 Приготовление полезных блюд\n• 💪 Баланс БЖУ\n\n🎯 Напишите в комментариях - наши эксперты дадут персональные рекомендации!",
            
            "🎯 **ЧЕЛЛЕНДЖ НЕДЕЛИ**: Приготовьте блюдо по нашему рецепту и:\n\n1. 📸 Сфотографируйте процесс/результат\n2. 💬 Опишите ваш опыт в комментариях\n3. 🏷️ Отметьте @ppsupershef\n\n🏆 Лучшие работы будут featured в сторис с экспертной оценкой!",
            
            "🤔 **ДИЛЕММА ПИТАНИЯ**: 'Стоит ли исключать углеводы для похудения?'\n\n🧬 Мнение нутрициолога: [скоро в комментариях]\n👨‍🍳 Мнение шефа: [скоро в комментариях]\n\n💬 Напишите ваше мнение - обсудим с экспертами!"
        ]
        
        return f"💎 ИНТЕРАКТИВ ПРЕМИУМ\n\n{theme}\n\n{interactions[weekday % len(interactions)]}"
    
    def _generate_expert_advice(self, weekday, theme):
        """Советы от команды экспертов"""
        prompt = f"""
        Дай комплексный совет по теме: {theme}
        
        Включи мнения всех экспертов:
        - Нутрициолог с 40-летним стажем (научная основа)
        - Шеф-повар Мишлен (практическое применение)  
        - Фитнес-тренер (интеграция с физической активностью)
        
        Формат:
        🧬 НУТРИЦИОЛОГ: [научное обоснование]
        👨‍🍳 ШЕФ: [практический совет]
        💪 ТРЕНЕР: [рекомендации по активности]
        """
        
        ai_content = self.ai_generator.generate_content(prompt, "advice")
        if ai_content:
            return f"🌟 КОМАНДА ЭКСПЕРТОВ\n\n{theme}\n\n{ai_content}"
        
        return self._get_static_expert_advice(weekday)
    
    def _add_expert_context(self, content_type):
        """Добавляет экспертный контекст к контенту"""
        experts = {
            'breakfast': "🧬 Нутрициолог: 'Завтрак задает метаболический тонус на весь день'",
            'lunch': "👨‍🍳 Шеф: 'Обед должен быть сбалансирован по текстурам и вкусам'", 
            'dinner': "💪 Тренер: 'Правильный ужин = качественное восстановление'",
            'science': "🧬 Научный подход: 'Питание - это биохимия, которую можно оптимизировать'",
            'visual': "🎨 Экспертная инфографика: 'Знание в идеальной форме'"
        }
        
        return f"\n\n{experts.get(content_type, '🌟 Команда экспертов @ppsupershef')}"
    
    def _get_elite_call_to_action(self):
        """Элитный призыв к действию"""
        return """

═══════════════════════════════

💎 **ПОНРАВИЛОСЬ? ПОДПИСЫВАЙТЕСЬ!**

👉 @ppsupershef - элитные знания о питании

💬 **КОММЕНТИРУЙТЕ!** Наши эксперты читают все комментарии и отвечают на лучшие вопросы

👇 **ОТМЕТЬТЕ РЕАКЦИЕЙ:**
❤️ - Вдохновляет | 🔥 - Применю | 📚 - Узнал новое

📤 **ПОДЕЛИТЕСЬ** с друзьями, которые ценят качество жизни!

🏷️ #ppsupershef #Мишлен #Нутрициология
"""
    
    # Статические методы как fallback
    def _get_static_breakfast(self, weekday):
        breakfasts = [
            "🥣 Овсянка с ягодами\n\n🥗 Ингредиенты:\n• Овсяные хлопья - 50г\n• Молоко - 200мл\n• Ягоды - 100г\n• Мед - 1 ч.л.\n\n👨‍🍳 Приготовление (10 минут):\n1. Залить овсянку молоком\n2. Варить 5 минут\n3. Добавить ягоды и мед\n\n📊 КБЖУ: 250 ккал",
            "🍳 Омлет с овощами\n\n🥗 Ингредиенты:\n• Яйца - 2 шт\n• Помидор - 1 шт\n• Перец - 0.5 шт\n• Зелень\n\n👨‍🍳 Приготовление (15 минут):\n1. Взбить яйца\n2. Обжарить овощи\n3. Залить яйцами\n4. Готовить под крышкой\n\n📊 КБЖУ: 280 ккал"
        ]
        return f"🌅 ЗАВТРАК ПРЕМИУМ\n\n{breakfasts[weekday % len(breakfasts)]}"
    
    def _get_static_lunch(self, weekday):
        lunches = [
            "🍲 Куриный суп\n\n🥗 Ингредиенты:\n• Куриная грудка - 150г\n• Картофель - 2 шт\n• Морковь - 1 шт\n• Лапша - 50г\n\n👨‍🍳 Приготовление (30 минут):\n1. Сварить бульон\n2. Добавить овощи\n3. Добавить лапшу\n\n📊 КБЖУ: 250 ккал"
        ]
        return f"🍽️ ОБЕД ПРЕМИУМ\n\n{lunches[weekday % len(lunches)]}"
    
    def _get_static_dinner(self, weekday):
        dinners = [
            "🍽️ Запеченная рыба\n\n🥗 Ингредиенты:\n• Рыба - 200г\n• Лимон - 0.5 шт\n• Зелень\n• Специи\n\n👨‍🍳 Приготовление (25 минут):\n1. Замариновать рыбу\n2. Запечь 20 минут\n3. Подать с лимоном\n\n📊 КБЖУ: 220 ккал"
        ]
        return f"🌙 УЖИН ПРЕМИУМ\n\n{dinners[weekday % len(dinners)]}"
    
    def _get_static_science(self, weekday):
        sciences = [
            "🧬 ЦИРКАДНЫЕ РИТМЫ\n\n📚 Научный факт: Прием пищи в правильное время суток ускоряет метаболизм на 10-15%\n\n💡 Практика: Завтракайте в течение часа после пробуждения, ужинайте за 3-4 часа до сна"
        ]
        return f"🔬 НАУКА ПИТАНИЯ\n\n{sciences[weekday % len(sciences)]}"
    
    def _get_static_expert_advice(self, weekday):
        advices = [
            "💎 СОВЕТ КОМАНДЫ\n\n🧬 Нутрициолог: 'Слушайте сигналы голода и насыщения'\n👨‍🍳 Шеф: 'Используйте свежие сезонные продукты'\n💪 Тренер: 'Сочетайте питание с регулярной активностью'"
        ]
        return f"🌟 ЭКСПЕРТНЫЙ СОВЕТ\n\n{advices[weekday % len(advices)]}"

    def run_elite_scheduler(self):
        """Запуск элитного расписания публикаций"""
        # Основные публикации
        schedule.every().day.at("09:00").do(lambda: self.publish_content('breakfast'))
        schedule.every().day.at("13:00").do(lambda: self.publish_content('lunch')) 
        schedule.every().day.at("15:00").do(lambda: self.publish_content('science'))
        schedule.every().day.at("18:00").do(lambda: self.publish_content('interactive'))
        schedule.every().day.at("19:00").do(lambda: self.publish_content('dinner'))
        schedule.every().day.at("21:00").do(lambda: self.publish_content('expert_advice'))
        
        # Визуальный контент (через день)
        if self.get_kemerovo_time().day % 2 == 0:
            schedule.every().day.at("16:00").do(lambda: self.publish_content('visual'))
        
        kemerovo_time = self.get_kemerovo_time()
        print(f"🎯 ЭЛИТНОЕ РАСПИСАНИЕ АКТИВИРОВАНО!")
        print(f"📍 Кемерово: {kemerovo_time.strftime('%H:%M')}")
        print(f"📱 Канал: @ppsupershef")
        print(f"🤖 Yandex GPT: {'✅' if self.ai_generator.yandex_gpt.is_active else '❌'}")
        print(f"🤖 DeepSeek: {'✅' if self.ai_generator.deepseek_gpt.is_active else '❌'}")
        print("📊 Расписание:")
        print("🥞 09:00 - Элитный завтрак")
        print("🍽️ 13:00 - Обед для продуктивности") 
        print("🧬 15:00 - Научные знания")
        print("💬 18:00 - Интерактив")
        print("🍽️ 19:00 - Ужин для восстановления")
        print("🌟 21:00 - Советы экспертов")
        print("🎨 16:00 - Визуал (через день)")
        print("=" * 50)
        
        # Тестовая отправка
        print("🧪 Тест элитной системы...")
        self.publish_content('breakfast')
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    def publish_content(self, content_type):
        """Публикация элитного контента"""
        kemerovo_time = self.get_kemerovo_time()
        print(f"📤 Публикация {content_type}... ({kemerovo_time.strftime('%H:%M')})")
        
        message = self.generate_elite_content(content_type)
        success = self.send_to_telegram(message)
        
        if success:
            print(f"✅ {content_type.upper()} успешно отправлен в @ppsupershef!")
        else:
            print(f"❌ Ошибка отправки {content_type}")
    
    def send_to_telegram(self, message):
        """Отправка сообщения в Telegram"""
        if not self.token or not self.channel:
            print("❌ Ошибка: Не установлен токен или канал!")
            return False
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            'chat_id': self.channel,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }
        
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                kemerovo_time = self.get_kemerovo_time()
                print(f"✅ Контент отправлен в @ppsupershef: {kemerovo_time.strftime('%H:%M')}")
                return True
            else:
                print(f"❌ Ошибка Telegram: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Ошибка соединения: {e}")
            return False

# Инициализация элитной системы
elite_channel = EliteContentManager()

def start_elite_scheduler():
    elite_channel.run_elite_scheduler()

scheduler_thread = Thread(target=start_elite_scheduler)
scheduler_thread.daemon = True
scheduler_thread.start()

@app.route('/')
def home():
    kemerovo_time = elite_channel.get_kemerovo_time()
    weekday = kemerovo_time.weekday()
    theme = elite_channel.content_strategy["weekly_themes"][weekday]
    
    return f"""
    <html>
        <head>
            <title>@ppsupershef - Элитная система</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                .status {{ padding: 10px; margin: 10px 0; border-radius: 5px; }}
                .success {{ background: #d4edda; color: #155724; }}
                .warning {{ background: #fff3cd; color: #856404; }}
                .schedule {{ background: #e2e3e5; padding: 15px; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>💎 @ppsupershef - Элитная система</h1>
                
                <div class="status success">
                    <strong>📍 Кемерово:</strong> {kemerovo_time.strftime('%H:%M')} | 
                    <strong>🎯 Тема:</strong> {theme} |
                    <strong>📱 Канал:</strong> @ppsupershef
                </div>
                
                <div class="status {'success' if elite_channel.ai_generator.yandex_gpt.is_active else 'warning'}">
                    <strong>🤖 Yandex GPT:</strong> {'✅ Активен' if elite_channel.ai_generator.yandex_gpt.is_active else '❌ Не настроен'}
                </div>
                
                <div class="status {'success' if elite_channel.ai_generator.deepseek_gpt.is_active else 'warning'}">
                    <strong>🤖 DeepSeek:</strong> {'✅ Активен' if elite_channel.ai_generator.deepseek_gpt.is_active else '❌ Не настроен'}
                </div>
                
                <div class="schedule">
                    <h3>🎯 Элитное расписание:</h3>
                    <ul>
                        <li>🥞 09:00 - Элитный завтрак</li>
                        <li>🍽️ 13:00 - Обед для продуктивности</li>
                        <li>🧬 15:00 - Научные знания</li>
                        <li>🎨 16:00 - Визуал (через день)</li>
                        <li>💬 18:00 - Интерактив</li>
                        <li>🍽️ 19:00 - Ужин для восстановления</li>
                        <li>🌟 21:00 - Советы экспертов</li>
                    </ul>
                </div>
                
                <p>
                    <a href="/test">🧪 Тест системы</a> | 
                    <a href="/force/breakfast">🚀 Принудительная отправка</a> |
                    <a href="/debug">🔧 Диагностика</a>
                </p>
            </div>
        </body>
    </html>
    """

@app.route('/test')
def test():
    test_message = "🧪 ТЕСТ ЭЛИТНОЙ СИСТЕМЫ\n\nСистема @ppsupershef работает в премиум-режиме! ✅\n\n💎 Подписывайтесь: @ppsupershef"
    success = elite_channel.send_to_telegram(test_message)
    return f"Тест отправлен в @ppsupershef: {'✅ Успешно' if success else '❌ Ошибка'}"

@app.route('/force/<content_type>')
def force_publish(content_type):
    valid_types = ['breakfast', 'lunch', 'dinner', 'science', 'visual', 'interactive', 'expert_advice']
    if content_type not in valid_types:
        return f"❌ Неверный тип. Используйте: {', '.join(valid_types)}"
    
    elite_channel.publish_content(content_type)
    return f"✅ Принудительно отправлен {content_type} в @ppsupershef"

@app.route('/debug')
def debug():
    kemerovo_time = elite_channel.get_kemerovo_time()
    return jsonify({
        "system": "@ppsupershef - Элитная система",
        "version": "2.0",
        "channel": "@ppsupershef",
        "kemerovo_time": kemerovo_time.strftime('%Y-%m-%d %H:%M:%S'),
        "ai_status": {
            "yandex_gpt": elite_channel.ai_generator.yandex_gpt.is_active,
            "deepseek": elite_channel.ai_generator.deepseek_gpt.is_active
        },
        "telegram": {
            "token_set": bool(TELEGRAM_TOKEN),
            "channel_set": bool(TELEGRAM_CHANNEL)
        },
        "status": "elite_active"
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Запуск элитной системы на порту {port}")
    print(f"💎 Канал: @ppsupershef")
    print(f"🎯 Режим: ПРЕМИУМ КОНТЕНТ")
    app.run(host='0.0.0.0', port=port)
