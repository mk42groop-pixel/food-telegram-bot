import os
import requests
import schedule
import time
import random
from datetime import datetime, timedelta, timezone
from threading import Thread
from flask import Flask
from dotenv import load_dotenv
import json

load_dotenv()
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL')
YANDEX_API_KEY = os.getenv('YANDEX_GPT_API_KEY')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')

class YandexGPT:
    def __init__(self):
        self.api_key = YANDEX_API_KEY
        self.folder_id = YANDEX_FOLDER_ID
        self.base_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        self.is_active = bool(self.api_key and self.folder_id)
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
                'maxTokens': 1500
            },
            'messages': [
                {
                    'role': 'user',
                    'text': prompt
                }
            ]
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=data, timeout=15)
            if response.status_code == 200:
                result = response.json()
                return result['result']['alternatives'][0]['message']['text']
            else:
                print(f"❌ Ошибка Yandex GPT API: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Ошибка соединения с Yandex GPT: {e}")
            return None

class VisualContentGenerator:
    def __init__(self):
        self.visual_content = {
            'infographics': [
                {
                    'title': '📊 ПРАВИЛО ТАРЕЛКИ',
                    'content': '• 1/2 тарелки - овощи/фрукты\n• 1/4 тарелки - белки\n• 1/4 тарелки - сложные углеводы\n\n🎯 Идеальный баланс для каждого приема пищи!',
                    'hashtags': '#ПравилоТарелки #БалансПитания #ИдеальнаяПорция'
                },
                {
                    'title': '📈 БАЛАНС БЖУ',
                    'content': '💪 Белки: 25-30%\n🥑 Жиры: 25-30%\n⚡ Углеводы: 40-50%\n\n📊 Оптимальное соотношение для здорового метаболизма!',
                    'hashtags': '#БалансБЖУ #Макросы #ПитаниеНаучно'
                },
                {
                    'title': '⏱️ ТАЙМИНГ ПРИЕМОВ ПИЩИ',
                    'content': '🕗 Завтрак: 7-9 утра\n🕛 Обед: 12-14 дня\n🕠 Ужин: 17-19 вечера\n\n⏰ Регулярность - ключ к стабильному метаболизму!',
                    'hashtags': '#ТаймингПитания #РежимДня #Метаболизм'
                },
                {
                    'title': '💧 ГИДРАТАЦИЯ В ТЕЧЕНИЕ ДНЯ',
                    'content': '☀️ Утро: 2 стакана воды\n🌞 День: 1.5 литра\n🌙 Вечер: 0.5 литра\n\n💦 Вода - основа всех метаболических процессов!',
                    'hashtags': '#Гидратация #ВодныйБаланс #ЗдоровыеПривычки'
                }
            ],
            'checklists': [
                {
                    'title': '✅ ЧЕК-ЛИСТ ПОЛЕЗНЫХ ПРОДУКТОВ',
                    'content': '🥦 Овощи: брокколи, шпинат, морковь\n🍎 Фрукты: яблоки, бананы, ягоды\n💪 Белки: курица, рыба, тофу\n🌾 Углеводы: киноа, гречка, овсянка\n🥑 Жиры: авокадо, орехи, оливковое масло',
                    'hashtags': '#ЧекЛист #ПолезныеПродукты #ЗдороваяКорзина'
                },
                {
                    'title': '🎒 СПИСОК ДЛЯ ЛАНЧБОКСА',
                    'content': '📦 Основа: крупа/салат\n🍗 Белок: курица/яйца/рыба\n🥬 Овощи: свежие/запеченные\n🍶 Заправка: отдельно\n🥤 Напиток: вода/чай\n\n💼 Идеальный обед на работе!',
                    'hashtags': '#Ланчбокс #ОбедНаРаботу #MealPrep'
                },
                {
                    'title': '📅 ПЛАН ПИТАНИЯ НА НЕДЕЛЮ',
                    'content': '🗓️ ПН: Рыбный день\n🗓️ ВТ: Куриный день\n🗓️ СР: Вегетарианский\n🗓️ ЧТ: Бобовый\n🗓️ ПТ: Разнообразный\n🗓️ СБ: Семейный\n🗓️ ВС: Подготовительный',
                    'hashtags': '#ПланПитания #MealPlan #Организация'
                }
            ]
        }
    
    def get_random_infographic(self):
        return random.choice(self.visual_content['infographics'])
    
    def get_random_checklist(self):
        return random.choice(self.visual_content['checklists'])

class SmartFoodChannel:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.channel = TELEGRAM_CHANNEL
        self.timezone_offset = 7
        self.content_themes = self.get_weekly_themes()
        self.visual_gen = VisualContentGenerator()
        self.gpt = YandexGPT()
        
    def get_kemerovo_time(self):
        """Получаем текущее время в Кемерово (UTC+7)"""
        utc_time = datetime.now(timezone.utc)
        kemerovo_time = utc_time + timedelta(hours=self.timezone_offset)
        return kemerovo_time
    
    def get_weekly_themes(self):
        return {
            0: "🚀 Быстрые завтраки",
            1: "💼 Обеды для работы", 
            2: "⚡ Ужины за 20 минут",
            3: "🔍 Разбор мифов о питании",
            4: "💰 Бюджетные рецепты",
            5: "🎯 Спецпроекты",
            6: "❓ Ответы на вопросы"
        }
    
    def get_daily_content(self, meal_type):
        """Генерирует контент по дням недели и типу приема пищи"""
        kemerovo_time = self.get_kemerovo_time()
        weekday = kemerovo_time.weekday()
        theme = self.content_themes[weekday]
        
        content_generators = {
            'завтрак': self.generate_breakfast_content,
            'обед': self.generate_lunch_content,
            'ужин': self.generate_dinner_content,
            'перекус': self.generate_snack_content,
            'нутрициолог': self.generate_nutritionist_advice,
            'визуал': self.generate_visual_content,
            'интерактив': self.generate_interactive_question
        }
        
        content = content_generators[meal_type](weekday)
        
        # Добавляем дополнительный развлекательный контент для ужина
        if meal_type == 'ужин':
            entertainment = self.get_daily_entertainment(weekday)
            content += f"\n\n🎭 ВЕЧЕРНИЙ БЛОК\n{entertainment}"
        
        # Добавляем призыв к действию и ссылки (кроме визуального и интерактивного контента)
        if meal_type not in ['визуал', 'интерактив']:
            content += self.get_call_to_action()
            
        return content
    
    def generate_breakfast_content(self, weekday):
        """Генерация завтрака - автоматически использует GPT если есть ключи"""
        if self.gpt.is_active:
            gpt_content = self._generate_recipe_with_gpt('завтрак', weekday)
            if gpt_content:
                return f"🌅 ЗАВТРАК ДНЯ (сгенерирован Yandex GPT)\n\n{gpt_content}"
        
        # Статический контент как запасной вариант - 7 разных завтраков
        return self._static_breakfast(weekday)
    
    def generate_lunch_content(self, weekday):
        """Генерация обеда - автоматически использует GPT если есть ключи"""
        if self.gpt.is_active:
            gpt_content = self._generate_recipe_with_gpt('обед', weekday)
            if gpt_content:
                return f"🍽️ ОБЕД ДНЯ (сгенерирован Yandex GPT)\n\n{gpt_content}"
        
        # Статический контент как запасной вариант - 7 разных обедов
        return self._static_lunch(weekday)
    
    def generate_dinner_content(self, weekday):
        """Генерация ужина - автоматически использует GPT если есть ключи"""
        if self.gpt.is_active:
            gpt_content = self._generate_recipe_with_gpt('ужин', weekday)
            if gpt_content:
                return f"🌙 УЖИН ДНЯ (сгенерирован Yandex GPT)\n\n{gpt_content}"
        
        # Статический контент как запасной вариант - 7 разных ужинов
        return self._static_dinner(weekday)
    
    def generate_snack_content(self, weekday):
        """Генерация перекуса - автоматически использует GPT если есть ключи"""
        if self.gpt.is_active:
            gpt_content = self._generate_recipe_with_gpt('перекус', weekday)
            if gpt_content:
                return f"☕ ПЕРЕКУС ДНЯ (сгенерирован Yandex GPT)\n\n{gpt_content}"
        
        # Статический контент как запасной вариант - 7 разных перекусов
        return self._static_snack(weekday)
    
    def generate_nutritionist_advice(self, weekday):
        """Советы нутрициолога - автоматически использует GPT если есть ключи"""
        if self.gpt.is_active:
            prompt = f"""
            Создай совет от нутрициолога с 40-летним стажем на тему здорового питания.
            
            Тема дня: {self.content_themes[weekday]}
            
            Формат:
            💎 СОВЕТ НУТРИЦИОЛОГА
            
            👨‍⚕️ [Основной совет в кавычках]
            
            📚 НАУЧНОЕ ОБОСНОВАНИЕ: [Объяснение почему это работает]
            
            💡 ПРАКТИЧЕСКИЙ СОВЕТ: [Конкретное действие]
            
            Тон: авторитетный, дружелюбный, мотивирующий.
            """
            
            gpt_content = self.gpt.generate_text(prompt, temperature=0.8)
            if gpt_content:
                return f"{gpt_content}\n\n🌟 Нутрициолог с 40-летним стажем"
        
        # Статический контент как запасной вариант - 7 разных советов
        return self._static_advice(weekday)
    
    def _generate_recipe_with_gpt(self, meal_type, weekday):
        """Генерация рецепта через Yandex GPT"""
        themes = {
            'завтрак': ['быстрый и энергичный', 'питательный', 'легкий и полезный', 'необычный', 'бюджетный', 'особенный', 'расслабленный'],
            'обед': ['быстрый для рабочего дня', 'сбалансированный', 'легкий но сытный', 'с необычными ингредиентами', 'экономный', 'особенный', 'семейный'],
            'ужин': ['легкий после работы', 'быстрый', 'полезный за 20 минут', 'развенчивающий мифы', 'бюджетный', 'особенный', 'расслабленный'],
            'перекус': ['полезный', 'быстрый', 'энергичный', 'вкусный', 'питательный', 'легкий', 'витаминный']
        }
        
        prompt = f"""
        Создай рецепт {meal_type}а для {themes[meal_type][weekday]}.
        
        Требования к формату:
        🍳 НАЗВАНИЕ БЛЮДА (с эмодзи)
        
        🥗 ИНГРЕДИЕНТЫ:
        • Список ингредиентов с количествами
        
        👨‍🍳 ПРИГОТОВЛЕНИЕ (укажи время):
        1. Шаг 1
        2. Шаг 2  
        3. Шаг 3
        
        📊 КБЖУ: приблизительная калорийность и польза
        
        Рецепт должен быть простым, полезным и доступным для приготовления дома.
        Используй вкусные описания и практичные советы.
        """
        
        return self.gpt.generate_text(prompt)
    
    def _static_breakfast(self, weekday):
        """Статический завтрак - 7 разных вариантов"""
        breakfasts = [
            "🥣 Овсянка с ягодами\n\n🥗 Ингредиенты:\n• Овсяные хлопья - 50г\n• Молоко - 200мл\n• Ягоды - 100г\n• Мед - 1 ч.л.\n\n👨‍🍳 Приготовление (10 минут):\n1. Залить овсянку молоком\n2. Варить 5 минут\n3. Добавить ягоды и мед\n\n📊 КБЖУ: 250 ккал",
            "🍳 Омлет с овощами\n\n🥗 Ингредиенты:\n• Яйца - 2 шт\n• Помидор - 1 шт\n• Перец - 0.5 шт\n• Зелень\n\n👨‍🍳 Приготовление (15 минут):\n1. Взбить яйца\n2. Обжарить овощи\n3. Залить яйцами\n4. Готовить под крышкой\n\n📊 КБЖУ: 280 ккал",
            "🥞 Творог с фруктами\n\n🥗 Ингредиенты:\n• Творог 5% - 150г\n• Банан - 1 шт\n• Мед - 1 ч.л.\n• Орехи - 20г\n\n👨‍🍳 Приготовление (3 минуты):\n1. Смешать творог с медом\n2. Добавить нарезанные фрукты\n3. Посыпать орехами\n\n📊 КБЖУ: 220 ккал",
            "🍲 Гречневая каша\n\n🥗 Ингредиенты:\n• Гречка - 50г\n• Вода - 150мл\n• Молоко - 100мл\n• Сливочное масло - 10г\n\n👨‍🍳 Приготовление (20 минут):\n1. Промыть гречку\n2. Варить 15 минут\n3. Добавить молоко и масло\n\n📊 КБЖУ: 200 ккал",
            "🥪 Цельнозерновой тост\n\n🥗 Ингредиенты:\n• Хлеб цельнозерновой - 2 ломтика\n• Авокадо - 0.5 шт\n• Яйцо - 1 шт\n• Специи\n\n👨‍🍳 Приготовление (10 минут):\n1. Поджарить хлеб\n2. Размять авокадо\n3. Приготовить яйцо\n4. Собрать тост\n\n📊 КБЖУ: 300 ккал",
            "🍓 Смузи из ягод\n\n🥗 Ингредиенты:\n• Ягоды замороженные - 100г\n• Йогурт - 150г\n• Банан - 1 шт\n• Мед - 1 ч.л.\n\n👨‍🍳 Приготовление (5 минут):\n1. Смешать все ингредиенты\n2. Взбить блендером\n3. Подать охлажденным\n\n📊 КБЖУ: 180 ккал",
            "🍚 Рисовая каша\n\n🥗 Ингредиенты:\n• Рис круглый - 50г\n• Молоко - 200мл\n• Тыква - 100г\n• Корица\n\n👨‍🍳 Приготовление (25 минут):\n1. Варить рис с тыквой\n2. Добавить молоко\n3. Посыпать корицей\n\n📊 КБЖУ: 230 ккал"
        ]
        return f"🌅 ЗАВТРАК ДНЯ\n\n{breakfasts[weekday]}"
    
    def _static_lunch(self, weekday):
        """Статический обед - 7 разных вариантов"""
        lunches = [
            "🍲 Куриный суп\n\n🥗 Ингредиенты:\n• Куриная грудка - 150г\n• Картофель - 2 шт\n• Морковь - 1 шт\n• Лапша - 50г\n\n👨‍🍳 Приготовление (30 минут):\n1. Сварить бульон\n2. Добавить овощи\n3. Добавить лапшу\n\n📊 КБЖУ: 250 ккал",
            "🥘 Гречка с грибами\n\n🥗 Ингредиенты:\n• Гречка - 100г\n• Шампиньоны - 200г\n• Лук - 1 шт\n• Сметана - 30г\n\n👨‍🍳 Приготовление (25 минут):\n1. Приготовить гречку\n2. Обжарить грибы с луком\n3. Смешать со сметаной\n\n📊 КБЖУ: 320 ккал",
            "🍝 Паста с морепродуктами\n\n🥗 Ингредиенты:\n• Паста - 100г\n• Креветки - 150г\n• Чеснок - 2 зубчика\n• Сливки - 50мл\n\n👨‍🍳 Приготовление (20 минут):\n1. Отварить пасту\n2. Обжарить креветки\n3. Смешать со сливками\n\n📊 КБЖУ: 380 ккал",
            "🥗 Салат с тунцом\n\n🥗 Ингредиенты:\n• Тунец консервированный - 1 банка\n• Яйца - 2 шт\n• Огурцы - 2 шт\n• Листья салата\n\n👨‍🍳 Приготовление (15 минут):\n1. Нарезать овощи\n2. Добавить тунец и яйца\n3. Заправить маслом\n\n📊 КБЖУ: 280 ккал",
            "🍛 Овощное рагу\n\n🥗 Ингредиенты:\n• Индейка - 150г\n• Кабачок - 1 шт\n• Баклажан - 1 шт\n• Помидоры - 2 шт\n\n👨‍🍳 Приготовление (30 минут):\n1. Обжарить индейку\n2. Добавить овощи\n3. Тушить 20 минут\n\n📊 КБЖУ: 300 ккал",
            "🍕 Домашняя пицца\n\n🥗 Ингредиенты:\n• Тесто - 150г\n• Помидоры - 2 шт\n• Сыр - 100г\n• Курица - 100г\n\n👨‍🍳 Приготовление (25 минут):\n1. Раскатать тесто\n2. Выложить начинку\n3. Запечь 20 минут\n\n📊 КБЖУ: 350 ккал",
            "🥘 Чечевичный суп\n\n🥗 Ингредиенты:\n• Чечевица - 100г\n• Морковь - 1 шт\n• Лук - 1 шт\n• Картофель - 2 шт\n\n👨‍🍳 Приготовление (35 минут):\n1. Варить чечевицу\n2. Добавить овощи\n3. Варить до готовности\n\n📊 КБЖУ: 270 ккал"
        ]
        return f"🍽️ ОБЕД ДНЯ\n\n{lunches[weekday]}"
    
    def _static_dinner(self, weekday):
        """Статический ужин - 7 разных вариантов"""
        dinners = [
            "🍽️ Запеченная рыба\n\n🥗 Ингредиенты:\n• Рыба - 200г\n• Лимон - 0.5 шт\n• Зелень\n• Специи\n\n👨‍🍳 Приготовление (25 минут):\n1. Замариновать рыбу\n2. Запечь 20 минут\n3. Подать с лимоном\n\n📊 КБЖУ: 220 ккал",
            "🥗 Салат с курицей\n\n🥗 Ингредиенты:\n• Куриная грудка - 150г\n• Огурцы - 2 шт\n• Помидоры - 2 шт\n• Листья салата\n\n👨‍🍳 Приготовление (15 минут):\n1. Приготовить курицу\n2. Нарезать овощи\n3. Смешать с заправкой\n\n📊 КБЖУ: 250 ккал",
            "🍲 Тушеные овощи\n\n🥗 Ингредиенты:\n• Тофу - 150г\n• Брокколи - 200г\n• Морковь - 1 шт\n• Соевый соус\n\n👨‍🍳 Приготовление (20 минут):\n1. Обжарить тофу\n2. Добавить овощи\n3. Тушить 15 минут\n\n📊 КБЖУ: 200 ккал",
            "🍗 Куриные котлеты\n\n🥗 Ингредиенты:\n• Куриный фарш - 200г\n• Лук - 1 шт\n• Яйцо - 1 шт\n• Панировка\n\n👨‍🍳 Приготовление (25 минут):\n1. Смешать фарш\n2. Сформировать котлеты\n3. Приготовить на пару\n\n📊 КБЖУ: 280 ккал",
            "🥘 Омлет со шпинатом\n\n🥗 Ингредиенты:\n• Яйца - 3 шт\n• Шпинат - 100г\n• Сыр - 50г\n• Молоко - 50мл\n\n👨‍🍳 Приготовление (15 минут):\n1. Взбить яйца\n2. Добавить шпинат\n3. Запечь в духовке\n\n📊 КБЖУ: 300 ккал",
            "🍤 Креветки с авокадо\n\n🥗 Ингредиенты:\n• Креветки - 200г\n• Авокадо - 1 шт\n• Лимон - 0.5 шт\n• Зелень\n\n👨‍🍳 Приготовление (15 минут):\n1. Обжарить креветки\n2. Нарезать авокадо\n3. Смешать с лимоном\n\n📊 КБЖУ: 260 ккал",
            "🥦 Брокколи с сыром\n\n🥗 Ингредиенты:\n• Брокколи - 300г\n• Сыр - 80г\n• Чеснок - 2 зубчика\n• Сливки - 50мл\n\n👨‍🍳 Приготовление (20 минут):\n1. Приготовить брокколи\n2. Сделать сырный соус\n3. Запечь в духовке\n\n📊 КБЖУ: 230 ккал"
        ]
        return f"🌙 УЖИН ДНЯ\n\n{dinners[weekday]}"
    
    def _static_snack(self, weekday):
        """Статический перекус - 7 разных вариантов"""
        snacks = [
            "🍎 Яблоко с миндалем\n\n🥗 Ингредиенты:\n• Яблоко - 1 шт\n• Миндаль - 30г\n• Корица\n\n👨‍🍳 Приготовление (2 минуты):\n1. Нарезать яблоко\n2. Посыпать орехами\n3. Добавить корицу\n\n📊 КБЖУ: 180 ккал",
            "🥛 Йогурт с гранолой\n\n🥗 Ингредиенты:\n• Греческий йогурт - 150г\n• Гранола - 30г\n• Ягоды - 50г\n\n👨‍🍳 Приготовление (2 минуты):\n1. Налить йогурт\n2. Добавить гранолу\n3. Посыпать ягодами\n\n📊 КБЖУ: 200 ккал",
            "🍌 Банан с арахисовой пастой\n\n🥗 Ингредиенты:\n• Банан - 1 шт\n• Арахисовая паста - 20г\n• Мед - 1 ч.л.\n\n👨‍🍳 Приготовление (3 минуты):\n1. Нарезать банан\n2. Намазать пасту\n3. Полить медом\n\n📊 КБЖУ: 220 ккал",
            "🥕 Морковные палочки\n\n🥗 Ингредиенты:\n• Морковь - 2 шт\n• Хумус - 50г\n• Кунжут\n\n👨‍🍳 Приготовление (5 минут):\n1. Нарезать морковь\n2. Подать с хумусом\n3. Посыпать кунжутом\n\n📊 КБЖУ: 150 ккал",
            "🍓 Ягоды с творогом\n\n🥗 Ингредиенты:\n• Творог - 100г\n• Смесь ягод - 100г\n• Мед - 1 ч.л.\n\n👨‍🍳 Приготовление (3 минуты):\n1. Смешать творог с медом\n2. Добавить ягоды\n3. Подать охлажденным\n\n📊 КБЖУ: 180 ккал",
            "🌰 Смесь орехов\n\n🥗 Ингредиенты:\n• Грецкие орехи - 20г\n• Миндаль - 20г\n• Кешью - 20г\n• Изюм - 20г\n\n👨‍🍳 Приготовление (1 минута):\n1. Смешать орехи\n2. Добавить изюм\n3. Разделить на порции\n\n📊 КБЖУ: 250 ккал",
            "🍅 Помидоры с моцареллой\n\n🥗 Ингредиенты:\n• Помидоры - 2 шт\n• Моцарелла - 100г\n• Базилик\n• Оливковое масло\n\n👨‍🍳 Приготовление (5 минут):\n1. Нарезать помидоры\n2. Добавить моцареллу\n3. Заправить маслом\n\n📊 КБЖУ: 200 ккал"
        ]
        return f"☕ ПЕРЕКУС ДНЯ\n\n{snacks[weekday]}"
    
    def _static_advice(self, weekday):
        """Статический совет нутрициолога - 7 разных советов"""
        advices = [
            "💎 СОВЕТ НУТРИЦИОЛОГА\n\n👨‍⚕️ «Начинайте день со стакана теплой воды - это запускает метаболизм»\n\n📚 НАУЧНОЕ ОБОСНОВАНИЕ: Вода активизирует работу ЖКТ после ночного перерыва\n\n💡 ПРАКТИЧЕСКИЙ СОВЕТ: Добавьте дольку лимона для усиления эффекта\n\n🌟 Нутрициолог с 40-летним стажем",
            "💎 СОВЕТ НУТРИЦИОЛОГА\n\n👨‍⚕️ «Пережевывайте пищу не менее 20 раз - это улучшает пищеварение»\n\n📚 НАУЧНОЕ ОБОСНОВАНИЕ: Тщательное пережевывание подготавливает пищу к лучшему усвоению\n\n💡 ПРАКТИЧЕСКИЙ СОВЕТ: Кладите вилку на стол между укусами\n\n🌟 Нутрициолог с 40-летним стажем",
            "💎 СОВЕТ НУТРИЦИОЛОГА\n\n👨‍⚕️ «Ужинайте за 3-4 часа до сна для качественного отдыха»\n\n📚 НАУЧНОЕ ОБОСНОВАНИЕ: Поздний прием пищи мешает выработке мелатонина\n\n💡 ПРАКТИЧЕСКИЙ СОВЕТ: Если голодны перед сном - выпейте кефир\n\n🌟 Нутрициолог с 40-летним стажем",
            "💎 СОВЕТ НУТРИЦИОЛОГА\n\n👨‍⚕️ «Съедайте 5 разных овощей в день для получения всех витаминов»\n\n📚 НАУЧНОЕ ОБОСНОВАНИЕ: Разноцветные овощи содержат разные фитонутриенты\n\n💡 ПРАКТИЧЕСКИЙ СОВЕТ: Используйте правило радуги в тарелке\n\n🌟 Нутрициолог с 40-летним стажем",
            "💎 СОВЕТ НУТРИЦИОЛОГА\n\n👨‍⚕️ «Белковая пища утром снижает тягу к сладкому вечером»\n\n📚 НАУЧНОЕ ОБОСНОВАНИЕ: Белок стабилизирует уровень сахара в крови\n\n💡 ПРАКТИЧЕСКИЙ СОВЕТ: Добавьте яйцо или творог к завтраку\n\n🌟 Нутрициолог с 40-летним стажем",
            "💎 СОВЕТ НУТРИЦИОЛОГА\n\n👨‍⚕️ «Пейте воду за 30 минут до еды для контроля аппетита»\n\n📚 НАУЧНОЕ ОБОСНОВАНИЕ: Вода заполняет желудок и снижает потребление калорий\n\n💡 ПРАКТИЧЕСКИЙ СОВЕТ: Поставьте бутылку с водой на рабочий стол\n\n🌟 Нутрициолог с 40-летним стажем",
            "💎 СОВЕТ НУТРИЦИОЛОГА\n\n👨‍⚕️ «Слушайте свой организм - он лучше знает, когда и что есть»\n\n📚 НАУЧНОЕ ОБОСНОВАНИЕ: Интуитивное питание снижает риск переедания\n\n💡 ПРАКТИЧЕСКИЙ СОВЕТ: Спросите себя «Я действительно голоден?» перед едой\n\n🌟 Нутрициолог с 40-летним стажем"
        ]
        return advices[weekday]
    
    def generate_visual_content(self, weekday):
        """Генерация визуального контента"""
        # Чередуем инфографику и чек-листы
        if weekday % 2 == 0:
            visual = self.visual_gen.get_random_infographic()
        else:
            visual = self.visual_gen.get_random_checklist()
        
        message = f"🎨 {visual['title']}\n\n"
        message += f"{visual['content']}\n\n"
        message += f"{visual['hashtags']}\n\n"
        message += "👇 Сохраните себе в закладки!"
        
        return message
    
    def generate_interactive_question(self, weekday):
        """Интерактивные вопросы для вовлечения"""
        questions = [
            "🍳 **ОПРОС: Какой завтрак вы предпочитаете?**\n\n• 🍓 Сладкий\n• 🥚 Соленый\n• 💪 Белковый\n• 🥤 Легкий\n\n💬 **Напишите в комментариях ваш вариант!**",
            "🍲 **ОПРОС: Что берете на обед?**\n\n• 🏠 Домашняя еда\n• 🍽️ Бизнес-ланч\n• 🥗 Салат/сэндвич\n• ⏰ Пропускаю\n\n💬 **Поделитесь вашими лайфхаками!**",
            "👨‍🍳 **ЧЕЛЛЕНДЖ НЕДЕЛИ**\n\nПриготовьте любой рецепт из канала и:\n1. 📸 Сфотографируйте\n2. 💬 Напишите в комментариях\n3. 🏷️ Отметьте @ppsupershef\n\n🎁 Лучшие работы - в сторис!",
            "💡 **СОВЕТ ДНЯ + ВОПРОС**\n\nЗнаете ли вы, что правильное сочетание белков и овощей улучшает усвоение питательных веществ на 30%?\n\n❓ **Вопрос: Какой ваш любимый способ приготовления овощей?**",
            "📊 **МИНИ-ОПРОС: Ваш режим питания**\n\nСколько раз в день вы едите?\n• 3 раза\n• 4-5 раз\n• 2 раза\n• По настроению\n\n💬 **Почему такой режим?**",
            "🎯 **ЗАДАНИЕ НА ВЫХОДНЫЕ**\n\n1. 🍽️ Приготовьте блюдо по рецепту\n2. 📸 Сделайте фото\n3. 📱 Выложите с тегом #ppsupershef\n\n🏆 Лучшие работы отметим!",
            "🤔 **ПРОБЛЕМА-РЕШЕНИЕ**\n\n🔴 Проблема: 'Не хватает времени на готовку'\n\n🟢 Решение: Meal Prep по воскресеньям!\n💬 **Какие ваши способы экономии времени?**"
        ]
        return questions[weekday]
    
    def get_daily_entertainment(self, weekday):
        """Развлекательный контент для ужина"""
        entertainment = [
            "💡 Совет вечера: Наслаждайтесь ужином без гаджетов - это улучшает пищеварение! 📵",
            "🌟 Факт: 20-минутная прогулка после ужина ускоряет метаболизм на 30%! 🚶‍♂️",
            "📚 Идея: Создайте вечерний ритуал - чай с травами и хорошая книга! 📖",
            "🏃‍♂️ Напоминание: Легкий ужин = качественный сон! 😴",
            "🥗 Рекомендация: Попробуйте новый овощ на ужин - расширяйте вкусовые горизонты! 🌈",
            "🎯 Челлендж: Готовьте ужин вместе с семьей - это сближает! 👨‍👩‍👧‍👦",
            "📝 Планирование: Составьте меню на следующую неделю сегодня вечером! 📅"
        ]
        return entertainment[weekday]
    
    def get_call_to_action(self):
        """Призыв к действию и ссылки"""
        cta = "\n\n" + "═" * 40 + "\n\n"
        cta += "📱 **ПОНРАВИЛОСЬ? ПОДПИСЫВАЙТЕСЬ!**\n\n"
        cta += "👉 @ppsupershef - ежедневные рецепты и советы от шефа\n\n"
        cta += "💬 **КОММЕНТИРУЙТЕ!** Напишите в комментариях:\n"
        cta += "• 📸 Ваши фото блюд\n• 💡 Ваши улучшения рецепта\n• ❓ Ваши вопросы шефу\n\n"
        cta += "👇 **ОТМЕТЬТЕ РЕАКЦИЕЙ:**\n"
        cta += "❤️ - Понравилось | 🔥 - Приготовлю | 👨‍🍳 - Уже готовил\n\n"
        cta += "📤 **ПОДЕЛИТЕСЬ** с друзьями!\n\n"
        cta += "🏷️ #ppsupershef"
        
        return cta
    
    def run_scheduler(self):
        """Запускает 7 публикаций в день по кемеровскому времени"""
        schedule.every().day.at("09:00").do(lambda: self.publish_meal('завтрак'))
        schedule.every().day.at("13:00").do(lambda: self.publish_meal('обед'))
        schedule.every().day.at("15:00").do(lambda: self.publish_meal('визуал'))
        schedule.every().day.at("16:00").do(lambda: self.publish_meal('перекус'))
        schedule.every().day.at("18:00").do(lambda: self.publish_meal('интерактив'))
        schedule.every().day.at("19:00").do(lambda: self.publish_meal('ужин'))
        schedule.every().day.at("21:30").do(lambda: self.publish_meal('нутрициолог'))
        
        kemerovo_time = self.get_kemerovo_time()
        print(f"📅 РАСПИСАНИЕ АКТИВИРОВАНО! Текущее время в Кемерово: {kemerovo_time.strftime('%H:%M')}")
        print(f"🤖 Yandex GPT: {'✅ Активен' if self.gpt.is_active else '❌ Не настроен'}")
        print("🥞 Завтрак: 09:00")
        print("🍲 Обед: 13:00") 
        print("🎨 Визуал: 15:00")
        print("🥜 Перекус: 16:00")
        print("💬 Интерактив: 18:00")
        print("🍽️ Ужин: 19:00")
        print("💎 Нутрициолог: 21:30")
        print("📱 Канал: @ppsupershef")
        print("=" * 50)
        
        # Тестовая отправка при запуске
        print("🧪 Тестовая отправка...")
        self.publish_meal('завтрак')
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    def publish_meal(self, meal_type):
        """Публикация контента"""
        kemerovo_time = self.get_kemerovo_time()
        print(f"📤 Публикация {meal_type}... ({kemerovo_time.strftime('%H:%M')} Кемерово)")
        message = self.get_daily_content(meal_type)
        success = self.send_to_telegram(message)
        
        if success:
            print(f"✅ {meal_type.capitalize()} успешно отправлен!")
        else:
            print(f"❌ Ошибка отправки {meal_type}")
    
    def send_to_telegram(self, message):
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
                print(f"✅ Сообщение отправлено: {kemerovo_time.strftime('%H:%M')} (Кемерово)")
                return True
            else:
                print(f"❌ Ошибка Telegram: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Ошибка соединения: {e}")
            return False

# Запуск системы
channel = SmartFoodChannel()

def start_scheduler():
    channel.run_scheduler()

scheduler_thread = Thread(target=start_scheduler)
scheduler_thread.daemon = True
scheduler_thread.start()

@app.route('/')
def home():
    kemerovo_time = channel.get_kemerovo_time()
    weekday = kemerovo_time.weekday()
    theme = channel.content_themes[weekday]
    gpt_status = "✅ Активен" if channel.gpt.is_active else "❌ Не настроен"
    
    return f"""
    <html>
        <body>
            <h1>🍳 Умная Кухня 7.0</h1>
            <p><strong>Кемерово:</strong> {kemerovo_time.strftime('%H:%M')}</p>
            <p><strong>Сегодня:</strong> {theme}</p>
            <p><strong>Yandex GPT:</strong> {gpt_status}</p>
            <p><strong>Канал:</strong> @ppsupershef</p>
            
            <p><strong>Расписание:</strong></p>
            <ul>
                <li>🥞 Завтрак: 09:00</li>
                <li>🍲 Обед: 13:00</li>
                <li>🎨 Визуал: 15:00</li>
                <li>🥜 Перекус: 16:00</li>
                <li>💬 Интерактив: 18:00</li>
                <li>🍽️ Ужин: 19:00</li>
                <li>💎 Нутрициолог: 21:30</li>
            </ul>
            
            <p><a href="/test">Тест отправки</a> | <a href="/debug">Диагностика</a></p>
        </body>
    </html>
    """

@app.route('/test')
def test():
    test_message = "🧪 ТЕСТОВОЕ СООБЩЕНИЕ\n\nБот работает! ✅\n\nПодписывайтесь: @ppsupershef"
    success = channel.send_to_telegram(test_message)
    return f"Тест отправлен: {'✅' if success else '❌'}"

@app.route('/force/<meal_type>')
def force_publish(meal_type):
    valid_meals = ['завтрак', 'обед', 'ужин', 'перекус', 'нутрициолог', 'визуал', 'интерактив']
    if meal_type not in valid_meals:
        return f"❌ Неверный тип. Используйте: {', '.join(valid_meals)}"
    
    channel.publish_meal(meal_type)
    return f"✅ Принудительно отправлен {meal_type}"

@app.route('/debug')
def debug():
    kemerovo_time = channel.get_kemerovo_time()
    return {
        "telegram_token_set": bool(TELEGRAM_TOKEN),
        "telegram_channel_set": bool(TELEGRAM_CHANNEL),
        "yandex_gpt_active": channel.gpt.is_active,
        "kemerovo_time": kemerovo_time.strftime('%Y-%m-%d %H:%M:%S'),
        "status": "active",
        "version": "7.0 - с автоматическим Yandex GPT"
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Запуск сервера на порту {port}")
    print(f"📱 Канал: @ppsupershef")
    app.run(host='0.0.0.0', port=port)
