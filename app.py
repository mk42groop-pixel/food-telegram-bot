import os
import requests
import schedule
import time
import random
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL')

class SmartFoodChannel:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.channel = TELEGRAM_CHANNEL
        # Кемерово UTC+7
        self.timezone_offset = 7
        self.content_themes = self.get_weekly_themes()
        
    def get_kemerovo_time(self):
        """Получаем текущее время в Кемерово (UTC+7)"""
        utc_time = datetime.utcnow()
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
            'перекус': self.generate_snack_content
        }
        
        content = content_generators[meal_type](weekday)
        
        # Добавляем дополнительный развлекательный контент для ужина
        if meal_type == 'ужин':
            entertainment = self.get_daily_entertainment(weekday)
            content += f"\n\n{entertainment}"
            
        return content
    
    def generate_breakfast_content(self, weekday):
        themes = {
            0: self.monday_breakfast, 1: self.tuesday_breakfast, 2: self.wednesday_breakfast,
            3: self.thursday_breakfast, 4: self.friday_breakfast, 5: self.saturday_breakfast,
            6: self.sunday_breakfast
        }
        return themes.get(weekday, self.default_breakfast)()
    
    def generate_lunch_content(self, weekday):
        themes = {
            0: self.monday_lunch, 1: self.tuesday_lunch, 2: self.wednesday_lunch,
            3: self.thursday_lunch, 4: self.friday_lunch, 5: self.saturday_lunch,
            6: self.sunday_lunch
        }
        return themes.get(weekday, self.default_lunch)()
    
    def generate_dinner_content(self, weekday):
        themes = {
            0: self.monday_dinner, 1: self.tuesday_dinner, 2: self.wednesday_dinner,
            3: self.thursday_dinner, 4: self.friday_dinner, 5: self.saturday_dinner,
            6: self.sunday_dinner
        }
        return themes.get(weekday, self.default_dinner)()
    
    def generate_snack_content(self, weekday):
        return self.default_snack()
    
    def get_daily_entertainment(self, weekday):
        """Дополнительный развлекательный контент для каждого дня"""
        entertainment = {
            0: self.monday_entertainment, 1: self.tuesday_entertainment, 2: self.wednesday_entertainment,
            3: self.thursday_entertainment, 4: self.friday_entertainment, 5: self.saturday_entertainment,
            6: self.sunday_entertainment
        }
        return entertainment.get(weekday, self.default_entertainment)()
    
    # РАЗВЛЕКАТЕЛЬНЫЙ КОНТЕНТ ПО ДНЯМ НЕДЕЛИ
    def monday_entertainment(self):
        return """🎥 ВИДЕО-РЕЛИЗ (сторис формат)
📹 "Завтрак за 5 минут: Успеваю до звонка на Zoom"
💡 Лайфхак дня: "Чтобы овсянка не пригорала, добавьте щепотку соли в самом начале"
        
#БыстрыеЗавтраки #УтреннийРитуал #Лайфхаки"""
    
    def tuesday_entertainment(self):
        return """📸 ФОТО ЛАНЧБОКСА
🍱 "Собираем обед с собой: Правило половинок"
🥗 1/2 - овощи, 1/4 - белок, 1/4 - углеводы
        
📊 ОПРОС: "В какой контейнер вы pack'аете обед?"
🔘 Стекло 🔘 Пластик 🔘 Многоразовый пакет
        
#ОбедыНаРаботу #MealPrep #ПравилоПоловинок"""
    
    def wednesday_entertainment(self):
        return """📈 ИНФОГРАФИКА
⚡ "Спасаем вечер: 3 шага до идеального ужина"
1. Нарезать курицу и овощи
2. Обжарить на сковороде  
3. Подать с зеленью
        
⭐ ИНГРЕДИЕНТ НЕДЕЛИ: АВОКАДО
🥑 Источник полезных жиров, витаминов Е и К
💡 Идея: Добавьте в салат или сделайте гуакамоле
        
#УжинЗа20Минут #Инфографика #АвокадоНедели"""
    
    def thursday_entertainment(self):
        myths = [
            {
                'myth': "❌ Углеводы после 18:00 превращаются в жир",
                'truth': "✅ Правда: Организму важен ОБЩИЙ калораж за день!"
            },
            {
                'myth': "❌ Чтобы похудеть, нужно есть только обезжиренные продукты", 
                'truth': "✅ Правда: В обезжиренных продуктах часто больше сахара!"
            },
            {
                'myth': "❌ Глютен - это зло для всех",
                'truth': "✅ Правда: Только 1% людей имеет целиакию!"
            }
        ]
        myth = random.choice(myths)
        return f"""🔍 РАЗБОР МИФА
        
{myth['myth']}
        
{myth['truth']}
        
💡 Научный факт: Баланс и умеренность - ключ к здоровому питанию!
        
#МифыОДиетологии #ПитаниеНаучно #РазрушаемМифы"""
    
    def friday_entertainment(self):
        budget_products = [
            {"name": "ГРЕЧКА", "recipes": "Гречневая каша, гречаники, гречка с грибами"},
            {"name": "КУРИНЫЕ БЕДРА", "recipes": "Запеченные бедра, суп, салат"},
            {"name": "КОНСЕРВИРОВАННАЯ ФАСОЛЬ", "recipes": "Салаты, супы, паштеты"}
        ]
        product = random.choice(budget_products)
        return f"""💰 БЮДЖЕТНЫЙ УЖИН
        
🍽️ "Ужин для двоих за 250 рублей"
📊 Расчет стоимости в описании
        
🛒 ПРОДУКТ-ВЫРУЧАЛКА: {product['name']}
📝 3 рецепта: {product['recipes']}
        
💡 Совет: Покупайте сезонные овощи - они дешевле и свежее!
        
#БюджетныеРецепты #ЭкономноеПитание #ПродуктВыручалка"""
    
    def saturday_entertainment(self):
        specials = [
            {
                'topic': "💪 СПОРТПИТ ДЛЯ НАЧИНАЮЩИХ",
                'content': "🍶 Протеиновый коктейль ДО тренировки - энергия\n🍶 Протеиновый коктейль ПОСЛЕ - восстановление\n⚠️ Не заменяйте полноценную еду добавками!",
                'checklist': "📋 5 признаков нехватки белка:\n1. Выпадение волос\n2. Постоянная усталость\n3. Частые болезни\n4. Ломкие ногти\n5. Медленное восстановление"
            },
            {
                'topic': "🌿 ДЕТОКС: ПРАВДА И МИФЫ", 
                'content': "🔄 Наше тело само очищается! Помогите ему:\n💧 Больше воды\n🥦 Клетчатка из овощей\n😴 Здоровый сон\n🚫 Минимум алкоголя",
                'checklist': "✅ Настоящий детокс - это:\n• Сбалансированное питание\n• Регулярная физическая активность\n• Качественный сон\n• Управление стрессом"
            }
        ]
        special = random.choice(specials)
        return f"""🎯 СПЕЦПРОЕКТ: {special['topic']}
        
{special['content']}
        
{special['checklist']}
        
🏋️ 💎 Совет эксперта: "Начинайте с 1г белка на кг веса"
        
#Спецпроект #ЭкспертныеМатериалы #Спортпит #Детокс"""
    
    def sunday_entertainment(self):
        qa_list = [
            {
                'question': '"Почему я не худею на дефиците калорий?"',
                'answer': '📝 Возможные причины:\n• Занижаете калории\n• Не учитываете соусы/напитки\n• Стресс и недосып\n• Плато - это нормально!'
            },
            {
                'question': '"Сколько раз в день нужно есть?"', 
                'answer': '📝 Главное - общее количество калорий и БЖУ!\n• 3-4 приема - комфортно для большинства\n• 1-2 приема - если удобно вам\n• Слушайте свой голод!'
            }
        ]
        qa = random.choice(qa_list)
        return f"""❓ ОТВЕТЫ НА ВОПРОСЫ
        
Вопрос от подписчика:
"{qa['question']}"
        
Наш ответ:
{qa['answer']}
        
💬 Есть вопросы? Пишите в комментариях - отвечаем каждое воскресенье!
📱 Можно задать вопрос через Google Forms (ссылка в описании канала)
        
#ВопросОтвет #ПомощьЭксперта #Консультация"""
    
    def default_entertainment(self):
        return "💡 Не забывайте пить воду и двигаться! Маленькие шаги приводят к большим результатам! 💪"
    
    # ОСНОВНЫЕ РЕЦЕПТЫ (сохранены из предыдущей версии)
    def monday_breakfast(self):
        return self.format_recipe({
            'name': '🥞 Быстрая овсянка с ягодами',
            'ingredients': ['Овсяные хлопья - 50г', 'Молоко - 200мл', 'Ягоды - 100г', 'Мед - 1 ч.л.'],
            'steps': ['Залить овсянку молоком', 'Микроволновка 3 минуты', 'Добавить ягоды и мед'],
            'time': '5 минут',
            'calories': '250 ккал'
        }, "🚀 ПОНЕДЕЛЬНИК: БЫСТРЫЕ ЗАВТРАКИ")
    
    def tuesday_lunch(self):
        return self.format_recipe({
            'name': '🍱 Ланчбокс: Курица с киноа',
            'ingredients': ['Куриная грудка - 150г', 'Киноа - 100г', 'Овощи - 200г', 'Соус - 30г'],
            'steps': ['Приготовить курицу и киноа', 'Нарезать овощи', 'Собрать по правилу половинок'],
            'time': '15 минут', 
            'calories': '400 ккал'
        }, "💼 ВТОРНИК: ОБЕДЫ ДЛЯ РАБОТЫ")
    
    def wednesday_dinner(self):
        return self.format_recipe({
            'name': '🍲 Лосось с брокколи',
            'ingredients': ['Лосось - 200г', 'Брокколи - 200г', 'Чеснок - 2 зубчика', 'Лимон - 0.5 шт'],
            'steps': ['Запечь лосось 15 мин', 'Приготовить брокколи на пару', 'Подать с лимоном'],
            'time': '20 минут',
            'calories': '350 ккал'
        }, "⚡ СРЕДА: УЖИНЫ ЗА 20 МИНУТ")
    
    def thursday_dinner(self):
        return self.format_recipe({
            'name': '🍛 Индейка с булгуром',
            'ingredients': ['Филе индейки - 200г', 'Булгур - 100г', 'Овощи - 250г', 'Специи'],
            'steps': ['Обжарить индейку', 'Приготовить булгур', 'Тушить с овощами 15 мин'],
            'time': '25 минут',
            'calories': '380 ккал'
        }, "🔍 ЧЕТВЕРГ: РАЗБОР МИФОВ")
    
    def friday_dinner(self):
        return self.format_recipe({
            'name': '🍝 Паста с тунцом',
            'ingredients': ['Паста - 80г (40₽)', 'Тунец консервированный - 1 банка (80₽)', 'Помидоры - 2 шт (30₽)', 'Лук - 1 шт (10₽)'],
            'steps': ['Отварить пасту', 'Обжарить лук и помидоры', 'Добавить тунца', 'Смешать с пастой'],
            'time': '20 минут',
            'calories': '420 ккал',
            'cost': '💰 Стоимость порции: ~80 рублей'
        }, "💰 ПЯТНИЦА: БЮДЖЕТНЫЕ РЕЦЕПТЫ")
    
    def default_breakfast(self):
        return self.format_recipe({
            'name': '🥣 Творог с фруктами',
            'ingredients': ['Творог 5% - 150г', 'Банан - 1 шт', 'Мед - 1 ч.л.', 'Орехи - 20г'],
            'steps': ['Смешать творог с медом', 'Добавить нарезанные фрукты', 'Посыпать орехами'],
            'time': '3 минуты',
            'calories': '220 ккал'
        }, "🌅 ЗАВТРАК ДНЯ")
    
    def default_lunch(self):
        return self.format_recipe({
            'name': '🍲 Суп-пюре из брокколи',
            'ingredients': ['Брокколи - 300г', 'Картофель - 2 шт', 'Лук - 1 шт', 'Сливки - 50мл'],
            'steps': ['Отварить овощи', 'Измельчить блендером', 'Добавить сливки'],
            'time': '20 минут', 
            'calories': '180 ккал'
        }, "🍽️ ОБЕД ДНЯ")
    
    def default_dinner(self):
        return self.format_recipe({
            'name': '🍗 Куриная грудка с овощами',
            'ingredients': ['Куриная грудка - 200г', 'Овощи - 300г', 'Специи', 'Оливковое масло'],
            'steps': ['Замариновать курицу', 'Запечь с овощами 25 мин', 'Подать горячим'],
            'time': '30 минут',
            'calories': '280 ккаl'
        }, "🌙 УЖИН ДНЯ")
    
    def default_snack(self):
        return self.format_recipe({
            'name': '🥜 Фруктовый салат с йогуртом',
            'ingredients': ['Яблоко - 1 шт', 'Банан - 1 шт', 'Йогурт - 100г', 'Мед - 1 ч.л.'],
            'steps': ['Нарезать фрукты', 'Заправить йогуртом', 'Добавить мед'],
            'time': '5 минут',
            'calories': '150 ккал'
        }, "☕ ПЕРЕКУС ДНЯ")
    
    def format_recipe(self, recipe, theme):
        message = f"{theme}\n\n"
        message += f"🍳 *{recipe['name']}*\n\n"
        
        message += "🥗 *Ингредиенты:*\n"
        for ing in recipe['ingredients']:
            message += f"• {ing}\n"
            
        message += f"\n👨‍🍳 *Приготовление ({recipe['time']}):*\n"
        for i, step in enumerate(recipe['steps'], 1):
            message += f"{i}. {step}\n"
            
        message += f"\n📊 *КБЖУ:* {recipe['calories']}\n"
        
        if 'cost' in recipe:
            message += f"\n{recipe['cost']}\n"
            
        message += "\n🔔 Подписывайтесь - каждый день новые полезные рецепты!"
        
        return message
    
    def send_to_telegram(self, message):
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
                print(f"❌ Ошибка: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Ошибка соединения: {e}")
            return False
    
    def run_scheduler(self):
        """Запускает 4 публикации в день по кемеровскому времени"""
        # РАСПИСАНИЕ ДЛЯ КЕМЕРОВО (UTC+7)
        schedule.every().day.at("06:00").do(lambda: self.publish_meal('завтрак'))
        schedule.every().day.at("12:00").do(lambda: self.publish_meal('обед'))
        schedule.every().day.at("17:00").do(lambda: self.publish_meal('ужин'))
        schedule.every().day.at("15:00").do(lambda: self.publish_meal('перекус'))
        
        kemerovo_time = self.get_kemerovo_time()
        print(f"📅 РАСПИСАНИЕ АКТИВИРОВАНО! Текущее время в Кемерово: {kemerovo_time.strftime('%H:%M')}")
        print("🥞 Завтрак: 06:00")
        print("🍲 Обед: 12:00") 
        print("🍽️ Ужин: 17:00")
        print("🥜 Перекус: 15:00")
        
        # Тестовая отправка при запуске
        print("🧪 Тестовая отправка завтрака...")
        self.publish_meal('завтрак')
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    def publish_meal(self, meal_type):
        """Публикация рецепта для конкретного приема пищи"""
        kemerovo_time = self.get_kemerovo_time()
        print(f"📤 Публикация {meal_type}... ({kemerovo_time.strftime('%H:%M')} Кемерово)")
        message = self.get_daily_content(meal_type)
        success = self.send_to_telegram(message)
        
        if success:
            print(f"✅ {meal_type.capitalize()} успешно отправлен!")
        else:
            print(f"❌ Ошибка отправки {meal_type}")

# Запуск системы
channel = SmartFoodChannel()

# Запуск в отдельном потоке
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
    return f"🍳 Умная Кухня 3.0 активна! Кемерово: {kemerovo_time.strftime('%H:%M')} | Сегодня: {theme}"

@app.route('/test')
def test():
    test_message = channel.get_daily_content('завтрак')
    channel.send_to_telegram("🧪 ТЕСТ: " + test_message[:100] + "...")
    return "Тест отправлен"

@app.route('/force/<meal_type>')
def force_publish(meal_type):
    """Принудительная отправка рецепта"""
    channel.publish_meal(meal_type)
    return f"Принудительно отправлен {meal_type}"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
