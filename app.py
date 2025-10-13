import os
import requests
import schedule
import time
import random
from datetime import datetime
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
        self.content_themes = self.get_weekly_themes()
        
    def get_weekly_themes(self):
        return {
            0: "🚀 Быстрые завтраки",  # Понедельник
            1: "💼 Обеды для работы",   # Вторник
            2: "⚡ Ужины за 20 минут",  # Среда
            3: "🔍 Разбор мифов",       # Четверг
            4: "💰 Бюджетные рецепты",  # Пятница
            5: "🎯 Спецпроекты",        # Суббота
            6: "❓ Ответы на вопросы"    # Воскресенье
        }
    
    def get_daily_content(self):
        """Генерирует контент по дням недели"""
        weekday = datetime.now().weekday()
        theme = self.content_themes[weekday]
        
        content_generators = {
            0: self.monday_breakfast,
            1: self.tuesday_lunch,
            2: self.wednesday_dinner,
            3: self.thursday_myths,
            4: self.friday_budget,
            5: self.saturday_special,
            6: self.sunday_qa
        }
        
        return content_generators[weekday]()
    
    def monday_breakfast(self):
        recipes = [
            {
                'name': '🥞 Овсянка с ягодами за 5 минут',
                'ingredients': ['Овсяные хлопья - 50г', 'Молоко - 200мл', 'Ягоды - 100г', 'Мед - 1 ч.л.'],
                'steps': ['Залить овсянку молоком', 'Микроволновка 3 минуты', 'Добавить ягоды и мед'],
                'time': '5 минут',
                'calories': '250 ккал',
                'lifehack': '💡 Лайфхак: Добавьте щепотку соли в овсянку - она не будет пригорать!',
                'video_idea': '🎥 Видео: "Завтрак за 5 минут до Zoom-звонка"'
            }
        ]
        return self.format_recipe(random.choice(recipes), "🚀 БЫСТРЫЕ ЗАВТРАКИ")
    
    def tuesday_lunch(self):
        recipes = [
            {
                'name': '🍱 Ланчбокс: Курица с киноа',
                'ingredients': ['Куриная грудка - 150г', 'Киноа - 100г', 'Овощи - 200г', 'Соус - 30г'],
                'steps': ['Приготовить курицу и киноа', 'Нарезать овощи', 'Собрать по правилу половинок'],
                'time': '15 минут',
                'calories': '400 ккал',
                'rule': '📐 Правило ланчбокса: 1/2 овощи, 1/4 белок, 1/4 углеводы',
                'poll': '📊 Опрос: В чем носите обед? (стекло/пластик/многоразовое)'
            }
        ]
        return self.format_recipe(random.choice(recipes), "💼 ОБЕДЫ ДЛЯ РАБОТЫ")
    
    def wednesday_dinner(self):
        recipes = [
            {
                'name': '🍲 Лосось с брокколи',
                'ingredients': ['Лосось - 200г', 'Брокколи - 200г', 'Чеснок - 2 зубчика', 'Лимон - 0.5 шт'],
                'steps': ['Запечь лосось 15 мин', 'Приготовить брокколи на пару', 'Подать с лимоном'],
                'time': '20 минут',
                'calories': '350 ккал',
                'infographic': '📈 3 шага: 1. Нарезать 2. Запечь 3. Подать',
                'ingredient_week': '⭐ Ингредиент недели: ЛОСОСЬ - источник Омега-3'
            }
        ]
        return self.format_recipe(random.choice(recipes), "⚡ УЖИНЫ ЗА 20 МИНУТ")
    
    def thursday_myths(self):
        myths = [
            {
                'myth': '❌ Углеводы после 18:00 превращаются в жир',
                'truth': '✅ Правда: Организму важен ОБЩИЙ калораж за день, а не время приема пищи!',
                'explanation': 'Можно есть углеводы вечером, если укладываетесь в норму калорий.'
            },
            {
                'myth': '❌ Обезжиренные продукты помогают похудеть',
                'truth': '✅ Правда: Часто в них добавляют больше сахара для вкуса!',
                'explanation': 'Натуральные жиры важны для гормонов и усвоения витаминов.'
            }
        ]
        myth = random.choice(myths)
        return self.format_myth(myth)
    
    def friday_budget(self):
        recipes = [
            {
                'name': '🍛 Гречка с грибами и луком',
                'ingredients': ['Гречка - 150г (30₽)', 'Шампиньоны - 200г (60₽)', 'Лук - 2 шт (20₽)', 'Сметана - 50г (25₽)'],
                'steps': ['Отварить гречку', 'Обжарить грибы с луком', 'Смешать со сметаной'],
                'time': '25 минут',
                'calories': '320 ккал',
                'cost': '💰 Стоимость порции: ~45 рублей',
                'product_tip': '🛒 Продукт-выручалка: ГРЕЧКА - хранится годами, готовится быстро!'
            }
        ]
        return self.format_recipe(random.choice(recipes), "💰 БЮДЖЕТНЫЕ РЕЦЕПТЫ")
    
    def saturday_special(self):
        specials = [
            {
                'topic': '💪 Спортпит для начинающих',
                'content': '• Протеин ДО тренировки - энергия\n• Протеин ПОСЛЕ - восстановление\n• Не заменяйте полноценную еду!',
                'expert_tip': '🏋️ Тренер советует: "Начинайте с 1г белка на кг веса"',
                'checklist': '📋 5 признаков нехватки белка: 1. Выпадение волос 2. Слабость 3. Частые болезни 4. Плохие ногти 5. Медленное восстановление'
            },
            {
                'topic': '🌿 Детокс: правда и мифы',
                'content': 'Наше тело само очищается! Помогите ему:\n• Больше воды\n• Клетчатка\n• Здоровый сон\n• Минимум алкоголя',
                'expert_tip': '🥦 Нутрициолог: "Детокс - это образ жизни, а не разовая акция"'
            }
        ]
        return self.format_special(random.choice(specials))
    
    def sunday_qa(self):
        qa_list = [
            {
                'question': '❓ "Почему я не худею на дефиците калорий?"',
                'answer': '📝 Возможные причины:\n• Занижаете калории\n• Не учитываете соусы/напитки\n• Стресс и недосып\n• Плато - это нормально!'
            },
            {
                'question': '❓ "Сколько раз в день нужно есть?"',
                'answer': '📝 Главное - общее количество калорий и БЖУ!\n• 3-4 приема - комфортно для большинства\n• 1-2 приема - если удобно вам\n• Слушайте свой голод!'
            }
        ]
        return self.format_qa(random.choice(qa_list))
    
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
        
        # Добавляем специальные поля
        if 'lifehack' in recipe:
            message += f"\n{recipe['lifehack']}\n"
        if 'rule' in recipe:
            message += f"\n{recipe['rule']}\n"
        if 'poll' in recipe:
            message += f"\n{recipe['poll']}\n"
        if 'infographic' in recipe:
            message += f"\n{recipe['infographic']}\n"
        if 'ingredient_week' in recipe:
            message += f"\n{recipe['ingredient_week']}\n"
        if 'cost' in recipe:
            message += f"\n{recipe['cost']}\n"
        if 'product_tip' in recipe:
            message += f"\n{recipe['product_tip']}\n"
        if 'video_idea' in recipe:
            message += f"\n{recipe['video_idea']}\n"
            
        message += f"\n#{theme.replace(' ', '').replace('-', '')}"
        message += "\n\n🔔 Подписывайтесь - каждый день новый полезный контент!"
        
        return message
    
    def format_myth(self, myth):
        message = "🔍 РАЗБОР МИФОВ О ПИТАНИИ\n\n"
        message += f"{myth['myth']}\n\n"
        message += f"{myth['truth']}\n\n"
        message += f"💡 {myth['explanation']}\n\n"
        message += "#МифыОДиетологии #ПитаниеНаучно"
        return message
    
    def format_special(self, special):
        message = "🎯 СПЕЦПРОЕКТ\n\n"
        message += f"*{special['topic']}*\n\n"
        message += f"{special['content']}\n\n"
        message += f"💎 {special['expert_tip']}\n\n"
        if 'checklist' in special:
            message += f"{special['checklist']}\n\n"
        message += "#ЭкспертныеМатериалы #Спецпроект"
        return message
    
    def format_qa(self, qa):
        message = "❓ ОТВЕТЫ НА ВОПРОСЫ\n\n"
        message += f"Вопрос от подписчика:\n{qa['question']}\n\n"
        message += f"Наш ответ:\n{qa['answer']}\n\n"
        message += "💬 Есть вопросы? Пишите в комментарии!\n"
        message += "#ВопросОтвет #ПомощьЭксперта"
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
                print(f"✅ Сообщение отправлено: {datetime.now().strftime('%H:%M')}")
                return True
            else:
                print(f"❌ Ошибка: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Ошибка соединения: {e}")
            return False
    
    def run_scheduler(self):
        """Запускает ежедневную публикацию"""
        schedule.every().day.at("09:00").do(self.daily_post)
        
        print("📅 Умный контент-план активирован!")
        print("Каждый день в 09:00 - новый тематический пост")
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    def daily_post(self):
        """Ежедневная публикация по контент-плану"""
        weekday = datetime.now().weekday()
        theme = self.content_themes[weekday]
        print(f"📤 Публикация: {theme}")
        
        message = self.get_daily_content()
        self.send_to_telegram(message)

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
    return "🍳 Умная Кухня 2.0 - Продвинутый контент-план активен!"

@app.route('/test')
def test():
    test_message = channel.get_daily_content()
    channel.send_to_telegram("🧪 ТЕСТ: " + test_message[:100] + "...")
    return "Тест отправлен"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
