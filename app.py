import os
import logging
import asyncio
from flask import Flask, request, jsonify, render_template
import requests
import json
from datetime import datetime, timedelta
import time
import schedule
from threading import Thread

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
    TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '-100362423055')  # Правильный ID канала
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
                    "channel_id": self.channel
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
                    'text': 'Ты эксперт по кулинарии, здоровому питанию и образу жизни. Создавай качественный, полезный контент.'
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
                    'maxTokens': 800
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
            "Создай рецепт полезного и быстрого завтрака на утро. Опиши ингредиенты, шаги приготовления и пользу для здоровья.",
            "Придумай идею питательного завтрака, который зарядит энергией на весь день. Укажи продукты и способ приготовления.",
            "Напиши рецепт вкусного и здорового завтрака с объяснением его преимуществ для организма."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt, 
            "Ты шеф-повар и нутрициолог. Создавай простые и полезные рецепты завтраков."
        )
        
        if content:
            return f"🍳 ЗАВТРАК\n\n{content}\n\n#завтрак #рецепт #здоровоепитание #утро"
        return self.get_fallback_content('breakfast')
    
    def generate_lunch(self):
        """Генерация контента для обеда"""
        prompts = [
            "Создай рецепт сбалансированного обеда для рабочего дня. Опиши блюдо, его питательную ценность и время приготовления.",
            "Придумай рецепт полезного обеда, который можно взять с собой. Укажи ингредиенты и способ хранения.",
            "Напиши о важности полноценного обеда и предложи вариант питательного блюда с рецептом."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты эксперт по здоровому питанию. Создавай рецепты обедов, которые насыщают и приносят пользу."
        )
        
        if content:
            return f"🍲 ОБЕД\n\n{content}\n\n#обед #рецепт #питание #здоровье"
        return self.get_fallback_content('lunch')
    
    def generate_science(self):
        """Генерация научного контента"""
        prompts = [
            "Расскажи о научном исследовании в области питания или кулинарии. Объясни простыми словами выводы и практическое применение.",
            "Напиши о интересном факте из науки о питании. Объясни его значение для повседневной жизни.",
            "Поделись научным открытием в области диетологии или пищевых технологий. Сделай акцент на практической пользе."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты ученый-диетолог. Объясняй научные концепции простым и доступным языком."
        )
        
        if content:
            return f"🔬 НАУКА\n\n{content}\n\n#наука #питание #факты #исследования"
        return self.get_fallback_content('science')
    
    def generate_interval(self):
        """Генерация контента про интервалы"""
        prompts = [
            "Напиши о пользе перерывов в питании и интервального голодания. Объясни основные принципы и преимущества.",
            "Расскажи о важности режима питания и перерывов между приемами пищи для метаболизма.",
            "Объясни, как правильно организовать интервалы между приемами пищи для максимальной пользы здоровью."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты эксперт по хронопитанию и метаболизму. Дай практические советы по timing питания."
        )
        
        if content:
            return f"⏱️ ИНТЕРВАЛ\n\n{content}\n\n#интервал #питание #метаболизм #здоровье"
        return self.get_fallback_content('interval')
    
    def generate_dinner(self):
        """Генерация контента для ужина"""
        prompts = [
            "Создай рецепт легкого и полезного ужина для хорошего сна и восстановления. Опиши ингредиенты и приготовление.",
            "Придумай вариант ужина, который не перегружает пищеварение перед сном. Объясни принципы вечернего питания.",
            "Напиши рецепт ужина, богатого триптофаном и магнием для качественного сна и восстановления."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты диетолог, специализирующийся на вечернем питании. Создавай легкие и полезные рецепты ужинов."
        )
        
        if content:
            return f"🍽️ УЖИН\n\n{content}\n\n#ужин #рецепт #здоровье #сон"
        return self.get_fallback_content('dinner')
    
    def generate_expert_advice(self):
        """Генерация совета эксперта"""
        prompts = [
            "Дай практический совет по улучшению пищевых привычек или кулинарных навыков.",
            "Поделись профессиональной рекомендацией по здоровому питанию для повседневной жизни.",
            "Напиши короткий, но ценный совет от эксперта в области питания и кулинарии."
        ]
        import random
        prompt = random.choice(prompts)
        
        content = self.generate_with_yandex_gpt(
            prompt,
            "Ты опытный нутрициолог и кулинарный эксперт. Дай краткий, но ценный совет."
        )
        
        if content:
            return f"💡 СОВЕТ ЭКСПЕРТА\n\n{content}\n\n#совет #эксперт #кулинария #здоровоепитание"
        return self.get_fallback_content('expert_advice')
    
    def get_fallback_content(self, content_type):
        """Резервный контент если генерация не сработала"""
        fallbacks = {
            'breakfast': "🍳 ЗАВТРАК\n\nНачните день с полезного завтрака! Овсянка с ягодами и орехами - отличный выбор для энергии и здоровья.\n\n#завтрак #здоровоепитание #утро",
            'lunch': "🍲 ОБЕД\n\nСбалансированный обед - залог продуктивного дня. Не пропускайте основной прием пищи!\n\n#обед #питание #здоровье",
            'science': "🔬 НАУКА\n\nИсследования показывают: регулярное питание улучшает метаболизм и поддерживает здоровый вес.\n\n#наука #питание #факты",
            'interval': "⏱️ ИНТЕРВАЛ\n\nПерерывы между приемами пищи важны для пищеварения. Оптимальный интервал - 3-4 часа.\n\n#интервал #питание #метаболизм",
            'dinner': "🍽️ УЖИН\n\nЛегкий ужин за 3 часа до сна способствует качественному отдыху и восстановлению.\n\n#ужин #здоровье #сон",
            'expert_advice': "💡 СОВЕТ ЭКСПЕРТА\n\nПейте воду за 30 минут до еды - это улучшает пищеварение и помогает контролировать аппетит.\n\n#совет #эксперт #здоровье"
        }
        logger.warning(f"⚠️ Использован резервный контент для {content_type}")
        return fallbacks.get(content_type, "Интересный контент скоро появится!")

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
                        logger.info(f"✅ Успешная публикация: {content_type}")
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
    return render_template('index.html', 
                         schedule=content_scheduler.get_schedule(),
                         next_time=next_time,
                         next_event=next_event,
                         channel_info=elite_channel.test_connection())

@app.route('/debug')
def debug():
    """Страница отладки"""
    connection_test = elite_channel.test_connection()
    next_time, next_event = content_scheduler.get_next_event()
    
    return jsonify({
        "telegram_channel_id": Config.TELEGRAM_CHANNEL,
        "bot_token_exists": bool(Config.TELEGRAM_BOT_TOKEN),
        "scheduler_status": "running" if content_scheduler.is_running else "stopped",
        "connection_test": connection_test,
        "next_scheduled_post": f"{next_time} - {next_event['name']}",
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
                "message": f"Неизвестный тип контента: {content_type}",
                "available_types": list(content_scheduler.schedule.keys())
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
                "message": f"Контент '{content_type}' отправлен в канал",
                "channel_id": Config.TELEGRAM_CHANNEL,
                "content_preview": content[:100] + "..."
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Не удалось отправить '{content_type}'. Проверьте логи."
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
        f"#тест #канал #работает"
    )
    
    success = elite_channel.send_to_telegram(test_message)
    connection_info = elite_channel.test_connection()
    
    return jsonify({
        "status": "success" if success else "error",
        "message": "Тестовое сообщение отправлено" if success else "Ошибка отправки",
        "connection_info": connection_info,
        "channel_id": Config.TELEGRAM_CHANNEL,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/schedule')
def get_schedule():
    """Получить расписание публикаций"""
    next_time, next_event = content_scheduler.get_next_event()
    
    return jsonify({
        "schedule": content_scheduler.get_schedule(),
        "next_post": {
            "time": next_time,
            "event": next_event,
            "timestamp": datetime.now().isoformat()
        },
        "scheduler_status": "running" if content_scheduler.is_running else "stopped"
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
            "connection_info": connection
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
        "scheduler_status": "running"
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
        "active_tasks": len(schedule.get_jobs()),
        "memory_usage": "OK"
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
    logger.info(f"🚀 Запуск приложения с каналом ID: {Config.TELEGRAM_CHANNEL}")
    logger.info(f"📅 Расписание: {list(content_scheduler.get_schedule().keys())}")
    
    # Финальная проверка подключения
    connection_test = elite_channel.test_connection()
    if connection_test.get('status') == 'success':
        logger.info(f"✅ Подключение к каналу успешно: {connection_test['channel']}")
    else:
        logger.error(f"❌ Проблемы с подключением: {connection_test}")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
