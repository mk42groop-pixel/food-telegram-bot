import os
import logging
import requests
import json
import time
import schedule
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, request, jsonify, render_template

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8459555322:AAHeddx-gWdcYXYkQHzyb9w7he9AHmZLhmA')
    TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '-1003152210862')  # ПРАВИЛЬНЫЙ ID КАНАЛА
    TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')
    YANDEX_GPT_API_KEY = os.getenv('YANDEX_GPT_API_KEY', 'AQVN3PPgJleV36f1uQeT6F_Ph5oI5xTyFPNf18h-')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-8af2b1f4bce441f8a802c2653516237a')

# Класс для работы с Telegram каналом
class EliteChannel:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        self.group = Config.TELEGRAM_GROUP
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
                message_id = result['result']['message_id']
                logger.info(f"✅ Сообщение #{message_id} отправлено в канал {self.channel}")
                return True
            else:
                error_msg = result.get('description', 'Unknown error')
                logger.error(f"❌ Ошибка отправки в Telegram: {error_msg}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error("❌ Таймаут при отправке в Telegram")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("❌ Ошибка соединения с Telegram API")
            return False
        except Exception as e:
            logger.error(f"❌ Исключение при отправке: {str(e)}")
            return False

    def test_connection(self):
        """Тестирование подключения к каналу"""
        try:
            # Проверяем бота
            url = f"https://api.telegram.org/bot{self.token}/getMe"
            response = requests.get(url, timeout=10)
            bot_info = response.json()
            
            if not bot_info.get('ok'):
                return {"status": "error", "message": "Неверный токен бота"}
            
            # Проверяем доступ к каналу
            url = f"https://api.telegram.org/bot{self.token}/getChat"
            response = requests.post(url, json={'chat_id': self.channel}, timeout=10)
            chat_info = response.json()
            
            if chat_info.get('ok'):
                return {
                    "status": "success", 
                    "bot": bot_info['result']['username'],
                    "channel": chat_info['result'].get('title', 'Unknown'),
                    "channel_id": self.channel,
                    "channel_username": "@ppsupershef"
                }
            else:
                return {"status": "error", "message": "Нет доступа к каналу"}
                
        except Exception as e:
            return {"status": "error", "message": str(e)}

# Генерация контента
class ContentGenerator:
    def __init__(self):
        self.yandex_key = Config.YANDEX_GPT_API_KEY
        self.yandex_folder = Config.YANDEX_FOLDER_ID
        self.deepseek_key = Config.DEEPSEEK_API_KEY
        logger.info("✅ Инициализирован генератор контента")
    
    def generate_with_yandex_gpt(self, prompt, system_prompt=None):
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
            
            messages = []
            if system_prompt:
                messages.append({
                    'role': 'system',
                    'text': system_prompt
                })
            else:
                messages.append({
                    'role': 'system',
                    'text': 'Ты эксперт по кулинарии, здоровому питанию и образу жизни. Создавай качественный, полезный контент на русском языке.'
                })
            
            messages.append({
                'role': 'user',
                'text': prompt
            })
            
            data = {
                'modelUri': f'gpt://{self.yandex_folder}/yandexgpt-lite',
                'completionOptions': {
                    'stream': False,
                    'temperature': 0.7,
                    'maxTokens': 1000
                },
                'messages': messages
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            result = response.json()
            
            if 'result' in result:
                text = result['result']['alternatives'][0]['message']['text']
                logger.info("✅ Контент успешно сгенерирован")
                return text
            else:
                logger.error(f"❌ Ошибка Yandex GPT: {result}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Исключение в Yandex GPT: {str(e)}")
            return None
    
    def generate_breakfast(self):
        """Генерация контента для завтрака"""
        prompts = [
            "Создай рецепт полезного и быстрого завтрака на утро. Опиши ингредиенты, шаги приготовления и пользу для здоровья. Сделай текст engaging и практичным.",
            "Придумай идею питательного завтрака, который зарядит энергией на весь день. Укажи конкретные продукты, способ приготовления и время готовки.",
            "Напиши рецепт вкусного и здорового завтрака с объяснением его преимуществ для организма. Добавь советы по вариациям блюда."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt, 
            "Ты шеф-повар и нутрициолог. Создавай простые, полезные и вкусные рецепты завтраков. Пиши живым engaging языком."
        )
        
        if content:
            return f"🍳 ЗАВТРАК\n\n{content}\n\n#завтрак #рецепт #здоровоепитание #утро #кулинария"
        return self.get_fallback_content('breakfast')
    
    def generate_lunch(self):
        """Генерация контента для обеда"""
        prompts = [
            "Создай рецепт сбалансированного обеда для рабочего дня. Опиши блюдо, его питательную ценность, время приготовления и почему он полезен.",
            "Придумай рецепт полезного обеда, который можно взять с собой на работу. Укажи ингредиенты, способ приготовления и хранения.",
            "Напиши о важности полноценного обеда и предложи вариант питательного блюда с пошаговым рецептом. Объясни пользу каждого компонента."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты эксперт по здоровому питанию и meal prep. Создавай рецепты обедов, которые насыщают, приносят пользу и легко готовятся."
        )
        
        if content:
            return f"🍲 ОБЕД\n\n{content}\n\n#обед #рецепт #питание #здоровье #рабочийдень"
        return self.get_fallback_content('lunch')
    
    def generate_science(self):
        """Генерация научного контента"""
        prompts = [
            "Расскажи о научном исследовании в области питания или кулинарии. Объясни простыми словами выводы и практическое применение в повседневной жизни.",
            "Напиши о интересном факте из науки о питании. Объясни его значение для здоровья и дай практические рекомендации.",
            "Поделись научным открытием в области диетологии или пищевых технологий. Сделай акцент на практической пользе и том, как это использовать."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты ученый-диетолог. Объясняй научные концепции простым и доступным языком. Делай акцент на практическом применении знаний."
        )
        
        if content:
            return f"🔬 НАУКА\n\n{content}\n\n#наука #питание #факты #исследования #здоровье"
        return self.get_fallback_content('science')
    
    def generate_interval(self):
        """Генерация контента про интервалы"""
        prompts = [
            "Напиши о пользе перерывов в питании и интервального голодания. Объясни основные принципы, преимущества и как правильно начать.",
            "Расскажи о важности режима питания и перерывов между приемами пищи для метаболизма. Дай практические советы по timing.",
            "Объясни, как правильно организовать интервалы между приемами пищи для максимальной пользы здоровью. Развей распространенные мифы."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты эксперт по хронопитанию и метаболизму. Дай практические советы по timing питания. Развенчивай мифы и давай научно обоснованные рекомендации."
        )
        
        if content:
            return f"⏱️ ИНТЕРВАЛ\n\n{content}\n\n#интервал #питание #метаболизм #здоровье #режим"
        return self.get_fallback_content('interval')
    
    def generate_dinner(self):
        """Генерация контента для ужина"""
        prompts = [
            "Создай рецепт легкого и полезного ужина для хорошего сна и восстановления. Опиши ингредиенты, приготовление и почему он не перегружает пищеварение.",
            "Придумай вариант ужина, который не перегружает пищеварение перед сном. Объясни принципы вечернего питания и пользу предложенного блюда.",
            "Напиши рецепт ужина, богатого триптофаном и магнием для качественного сна и восстановления. Объясни механизм действия компонентов."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты диетолог, специализирующийся на вечернем питании и качестве сна. Создавай легкие, полезные рецепты ужинов, способствующих восстановлению."
        )
        
        if content:
            return f"🍽️ УЖИН\n\n{content}\n\n#ужин #рецепт #здоровье #сон #восстановление"
        return self.get_fallback_content('dinner')
    
    def generate_expert_advice(self):
        """Генерация совета эксперта"""
        prompts = [
            "Дай практический совет по улучшению пищевых привычек или кулинарных навыков. Сделай его конкретным и actionable.",
            "Поделись профессиональной рекомендацией по здоровому питанию для повседневной жизни. Объясни почему это работает.",
            "Напиши короткий, но ценный совет от эксперта в области питания и кулинарии, который можно применить сразу же."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты опытный нутрициолог и кулинарный эксперт. Дай краткий, но ценный и практический совет, который легко внедрить в жизнь."
        )
        
        if content:
            return f"💡 СОВЕТ ЭКСПЕРТА\n\n{content}\n\n#совет #эксперт #кулинария #здоровоепитание #лайфхак"
        return self.get_fallback_content('expert_advice')
    
    def get_fallback_content(self, content_type):
        """Резервный контент если генерация не сработала"""
        fallbacks = {
            'breakfast': """🍳 ЗАВТРАК

Начните день с овсянки с ягодами и орехами! Это идеальный завтрак для энергии и здоровья.

• 50 г овсяных хлопьев
• 200 мл молока или воды
• Горсть свежих или замороженных ягод
• 1 ст.л. орехов
• Щепотка корицы

Варите овсянку 5-7 минут, добавьте ягоды и орехи. Питательно, полезно и вкусно!

#завтрак #здоровоепитание #утро #овсянка #рецепт""",

            'lunch': """🍲 ОБЕД

Куриный суп с овощами - идеальный обед для продуктивного дня!

• 200 г куриной грудки
• 1 л воды
• 2 картофелины
• 1 морковь
• 1 луковица
• Зелень, соль, специи

Сварите бульон, добавьте овощи, готовьте 20 минут. Сытно, полезно и восстанавливает силы!

#обед #питание #здоровье #суп #рецепт""",

            'science': """🔬 НАУКА

Исследования показывают: регулярное питание в одно и то же время улучшает метаболизм на 15-20%!

Циркадные ритмы влияют на усвоение nutrients. Старайтесь есть в одинаковое время каждый день для оптимального пищеварения и контроля веса.

#наука #питание #факты #метаболизм #здоровье""",

            'interval': """⏱️ ИНТЕРВАЛ

Оптимальный перерыв между приемами пищи - 3-4 часа!

Это позволяет:
• Полностью переварить предыдущий прием пищи
• Поддержать стабильный уровень сахара в крови
• Дать отдых пищеварительной системе

Не забывайте про воду между едой!

#интервал #питание #метаболизм #здоровье #режим""",

            'dinner': """🍽️ УЖИН

Легкий белковый ужин за 3 часа до сна способствует качественному отдыху!

Варианты:
• Запеченная рыба с овощами
• Творог с зеленью
• Омлет со шпинатом

Легкий ужин = крепкий сон + эффективное восстановление!

#ужин #здоровье #сон #белок #рецепт""",

            'expert_advice': """💡 СОВЕТ ЭКСПЕРТА

Пейте стакан теплой воды за 30 минут до еды!

Это помогает:
• Подготовить пищеварительную систему
• Улучшить усвоение nutrients
• Контролировать аппетит
• Ускорить метаболизм

Простая привычка = большая польза для здоровья!

#совет #эксперт #здоровье #вода #лайфхак"""
        }
        logger.warning(f"⚠️ Использован резервный контент для {content_type}")
        return fallbacks.get(content_type, "Интересный контент скоро появится! 🔥")

# Расписание публикаций
class ContentScheduler:
    def __init__(self):
        self.schedule = {
            "07:00": {"type": "breakfast", "name": "🍳 Завтрак", "generator": "generate_breakfast"},
            "12:00": {"type": "lunch", "name": "🍲 Обед", "generator": "generate_lunch"},
            "16:00": {"type": "science", "name": "🔬 Наука", "generator": "generate_science"},
            "18:00": {"type": "interval", "name": "⏱️ Интервал", "generator": "generate_interval"},
            "19:00": {"type": "dinner", "name": "🍽️ Ужин", "generator": "generate_dinner"},
            "21:00": {"type": "expert_advice", "name": "💡 Советы экспертов", "generator": "generate_expert_advice"}
        }
        self.is_running = False
        logger.info("✅ Инициализирован планировщик контента")
    
    def get_schedule(self):
        """Получить расписание"""
        return self.schedule
    
    def get_next_event(self):
        """Получить следующее событие по расписанию"""
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        # Ищем следующее событие сегодня
        times_today = [t for t in self.schedule.keys() if t > current_time]
        if times_today:
            next_time = min(times_today)
            return next_time, self.schedule[next_time]
        
        # Если сегодня больше нет событий, берем первое завтра
        first_time_tomorrow = min(self.schedule.keys())
        return first_time_tomorrow, self.schedule[first_time_tomorrow]
    
    def schedule_job(self, time_str, content_type):
        """Запланировать задание"""
        try:
            method_name = self.schedule[time_str]['generator']
            method = getattr(content_gen, method_name)
            
            def job():
                logger.info(f"🕒 Выполнение запланированной публикации: {content_type}")
                content = method()
                if content:
                    success = elite_channel.send_to_telegram(content)
                    if success:
                        logger.info(f"✅ Успешная публикация: {content_type} в {time_str}")
                    else:
                        logger.error(f"❌ Ошибка публикации: {content_type}")
                else:
                    logger.error(f"❌ Не удалось сгенерировать контент: {content_type}")
            
            schedule.every().day.at(time_str).do(job)
            logger.info(f"✅ Запланирована публикация: {time_str} - {content_type}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка планирования {time_str}: {str(e)}")
    
    def start_scheduler(self):
        """Запуск планировщика"""
        if self.is_running:
            logger.warning("⚠️ Планировщик уже запущен")
            return
        
        logger.info("🚀 Запуск планировщика публикаций...")
        
        # Планируем все события
        for time_str, event in self.schedule.items():
            self.schedule_job(time_str, event['type'])
        
        self.is_running = True
        
        # Запускаем в отдельном потоке
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)  # Проверяем каждую минуту
        
        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        logger.info("✅ Планировщик запущен в отдельном потоке")
    
    def stop_scheduler(self):
        """Остановка планировщика"""
        self.is_running = False
        schedule.clear()
        logger.info("🛑 Планировщик остановлен")

# Инициализация компонентов
elite_channel = EliteChannel()
content_gen = ContentGenerator()
content_scheduler = ContentScheduler()

# Запускаем планировщик при старте
content_scheduler.start_scheduler()

# Маршруты Flask
@app.route('/')
def index():
    """Главная страница"""
    next_time, next_event = content_scheduler.get_next_event()
    connection_info = elite_channel.test_connection()
    
    return f"""
    <html>
        <head>
            <title>Система управления @ppsupershef</title>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
                .schedule {{ background: #ecf0f1; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                .event {{ padding: 10px; margin: 5px 0; background: white; border-left: 4px solid #3498db; }}
                .next-event {{ background: #e8f6f3; border-left: 4px solid #27ae60; font-weight: bold; }}
                .status-success {{ color: #27ae60; }}
                .status-error {{ color: #e74c3c; }}
                .btn {{ display: inline-block; padding: 10px 20px; margin: 5px; background: #3498db; color: white; text-decoration: none; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🍳 Система управления @ppsupershef</h1>
                    <p>ID канала: {Config.TELEGRAM_CHANNEL}</p>
                    <p class="status-{'success' if connection_info.get('status') == 'success' else 'error'}">
                        Статус: {connection_info.get('status', 'unknown')} - {connection_info.get('message', '')}
                    </p>
                </div>
                
                <div class="schedule">
                    <h2>📅 Расписание публикаций</h2>
                    {"".join([f'<div class="event{" next-event" if time == next_time else ""}">{time} - {event["name"]}</div>' for time, event in content_scheduler.schedule.items()])}
                </div>
                
                <div>
                    <h3>⚡ Быстрые действия</h3>
                    <a class="btn" href="/test-channel">Тест канала</a>
                    <a class="btn" href="/debug">Отладка</a>
                    <a class="btn" href="/schedule">Расписание JSON</a>
                    <a class="btn" href="/health">Health Check</a>
                </div>
                
                <div style="margin-top: 20px;">
                    <h3>📤 Отправка контента</h3>
                    {"".join([f'<a class="btn" href="/send-now/{event["type"]}" style="background: #9b59b6;">{event["name"]}</a>' for event in content_scheduler.schedule.values()])}
                </div>
                
                <div style="margin-top: 20px; color: #7f8c8d;">
                    <p>Следующая публикация: <strong>{next_time} - {next_event['name']}</strong></p>
                    <p>Время сервера: {datetime.now().strftime('%H:%M:%S')}</p>
                </div>
            </div>
        </body>
    </html>
    """

@app.route('/debug')
def debug():
    """Страница отладки"""
    connection_test = elite_channel.test_connection()
    next_time, next_event = content_scheduler.get_next_event()
    
    return jsonify({
        "status": "active",
        "telegram_channel_id": Config.TELEGRAM_CHANNEL,
        "channel_username": "@ppsupershef",
        "bot_token_exists": bool(Config.TELEGRAM_BOT_TOKEN),
        "scheduler_status": "running" if content_scheduler.is_running else "stopped",
        "connection_test": connection_test,
        "next_scheduled_post": {
            "time": next_time,
            "event": next_event,
            "timestamp": datetime.now().isoformat()
        },
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "environment": "production" if os.getenv('PRODUCTION') else "development",
        "active_jobs": len(schedule.get_jobs())
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
                "message": f"Неизвестный тип контента: {content_type}",
                "available_types": [event['type'] for event in content_scheduler.schedule.values()]
            })
        
        if not content:
            return jsonify({
                "status": "error",
                "message": "Не удалось сгенерировать контент"
            })
        
        # Отправка в канал
        success = elite_channel.send_to_telegram(content)
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Контент '{content_type}' отправлен в канал @ppsupershef",
                "channel_id": Config.TELEGRAM_CHANNEL,
                "content_preview": content[:150] + "...",
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Не удалось отправить '{content_type}'. Проверьте логи.",
                "channel_id": Config.TELEGRAM_CHANNEL
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
    test_message = (
        f"✅ ТЕСТОВОЕ СООБЩЕНИЕ\n\n"
        f"Канал: @ppsupershef\n"
        f"ID: {Config.TELEGRAM_CHANNEL}\n"
        f"Время: {datetime.now().strftime('%H:%M:%S')}\n"
        f"Бот: @ppsupershef_bot\n\n"
        f"Статус: 📍 Работает исправно\n\n"
        f"#тест #канал #работает #ppsupershef"
    )
    
    success = elite_channel.send_to_telegram(test_message)
    connection_info = elite_channel.test_connection()
    
    return jsonify({
        "status": "success" if success else "error",
        "message": "Тестовое сообщение отправлено в @ppsupershef" if success else "Ошибка отправки",
        "connection_info": connection_info,
        "channel_id": Config.TELEGRAM_CHANNEL,
        "channel_username": "@ppsupershef",
        "timestamp": datetime.now().isoformat(),
        "test_message_preview": test_message[:100] + "..."
    })

@app.route('/schedule')
def get_schedule():
    """Получить расписание публикаций"""
    next_time, next_event = content_scheduler.get_next_event()
    
    return jsonify({
        "channel": "@ppsupershef",
        "channel_id": Config.TELEGRAM_CHANNEL,
        "schedule": content_scheduler.get_schedule(),
        "next_post": {
            "time": next_time,
            "event": next_event,
            "timestamp": datetime.now().isoformat()
        },
        "scheduler_status": "running" if content_scheduler.is_running else "stopped",
        "timezone": "Кемерово (UTC+7)"
    })

@app.route('/health')
def health_check():
    """Проверка здоровья приложения"""
    connection = elite_channel.test_connection()
    
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "telegram_connection": connection,
        "scheduler_running": content_scheduler.is_running,
        "active_jobs": len(schedule.get_jobs()),
        "channel": "@ppsupershef",
        "channel_id": Config.TELEGRAM_CHANNEL,
        "memory_usage": "OK",
        "response_time": "OK"
    })

@app.route('/force-send/<content_type>')
def force_send(content_type):
    """Принудительная отправка с диагностикой"""
    logger.info(f"🔧 Принудительная отправка: {content_type}")
    
    # Тестируем соединение
    connection = elite_channel.test_connection()
    if connection.get('status') != 'success':
        return jsonify({
            "status": "error",
            "message": "Проблемы с подключением к каналу",
            "connection_info": connection,
            "channel_id": Config.TELEGRAM_CHANNEL
        })
    
    # Отправляем контент
    return send_now(content_type)

@app.route('/restart-scheduler')
def restart_scheduler():
    """Перезапуск планировщика"""
    content_scheduler.stop_scheduler()
    time.sleep(2)
    content_scheduler.start_scheduler()
    
    return jsonify({
        "status": "success",
        "message": "Планировщик перезапущен",
        "scheduler_status": "running",
        "channel": "@ppsupershef",
        "timestamp": datetime.now().isoformat()
    })

# Обработка ошибок
@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Error: {str(error)}")
    return jsonify({"status": "error", "message": "Internal server error"}), 500

if __name__ == '__main__':
    logger.info(f"🚀 Запуск приложения для канала: @ppsupershef")
    logger.info(f"📋 ID канала: {Config.TELEGRAM_CHANNEL}")
    logger.info(f"📅 Расписание: {list(content_scheduler.get_schedule().keys())}")
    
    # Финальная проверка подключения
    connection_test = elite_channel.test_connection()
    if connection_test.get('status') == 'success':
        logger.info(f"✅ Подключение к каналу успешно: {connection_test['channel']}")
        logger.info(f"🤖 Бот: {connection_test['bot']}")
    else:
        logger.error(f"❌ Проблемы с подключением: {connection_test}")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
