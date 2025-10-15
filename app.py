import os
import logging
from flask import Flask, request, jsonify, render_template
import requests
import json
from datetime import datetime
import time

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8459555322:AAHeddx-gWdcYXYkQHzyb9w7he9AHmZLhmA')
    TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '-100362423055')  # ОБНОВЛЕННЫЙ ID
    TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')
    YANDEX_GPT_API_KEY = os.getenv('YANDEX_GPT_API_KEY', 'AQVN3PPgJleV36f1uQeT6F_Ph5oI5xTyFPNf18h-')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-8af2b1f4bce441f8a802c2653516237a')

# Класс для работы с Telegram каналом
class EliteChannel:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL  # Используем обновленный ID
        self.group = Config.TELEGRAM_GROUP
        logger.info(f"Инициализирован канал с ID: {self.channel}")
    
    def send_to_telegram(self, message, parse_mode='HTML'):
        """Отправка сообщения в Telegram канал"""
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                'chat_id': self.channel,
                'text': message,
                'parse_mode': parse_mode
            }
            
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"✅ Сообщение отправлено в канал {self.channel}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки: {result.get('description')}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Исключение при отправке: {str(e)}")
            return False

# Инициализация
elite_channel = EliteChannel()

# Генерация контента
class ContentGenerator:
    def __init__(self):
        self.yandex_key = Config.YANDEX_GPT_API_KEY
        self.yandex_folder = Config.YANDEX_FOLDER_ID
        self.deepseek_key = Config.DEEPSEEK_API_KEY
    
    def generate_with_yandex_gpt(self, prompt):
        """Генерация контента через Yandex GPT"""
        try:
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
                        'text': 'Ты эксперт по кулинарии и здоровому питанию. Создавай качественный контент.'
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
    
    def generate_expert_advice(self):
        """Генерация совета эксперта"""
        prompts = [
            "Создай полезный совет по кулинарии на сегодня",
            "Напиши короткий совет по здоровому питанию",
            "Дай рекомендацию по приготовлению полезного блюда"
        ]
        
        import random
        prompt = random.choice(prompts)
        content = self.generate_with_yandex_gpt(prompt)
        
        if content:
            return f"💡 СОВЕТ ЭКСПЕРТА:\n\n{content}\n\n#совет #кулинария #здоровоепитание"
        return None

# Инициализация генератора
content_gen = ContentGenerator()

# Маршруты Flask
@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/debug')
def debug():
    """Страница отладки"""
    return jsonify({
        "telegram_channel_id": Config.TELEGRAM_CHANNEL,
        "bot_token_exists": bool(Config.TELEGRAM_BOT_TOKEN),
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "active"
    })

@app.route('/send-now/<content_type>')
def send_now(content_type):
    """Немедленная отправка контента"""
    try:
        if content_type == 'expert_advice':
            content = content_gen.generate_expert_advice()
            if not content:
                return jsonify({
                    "status": "error",
                    "message": "Не удалось сгенерировать контент"
                })
        else:
            return jsonify({
                "status": "error", 
                "message": f"Неизвестный тип контента: {content_type}"
            })
        
        # Отправка в канал
        success = elite_channel.send_to_telegram(content)
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Контент {content_type} отправлен в канал",
                "channel_id": Config.TELEGRAM_CHANNEL
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Не удалось отправить {content_type}. Проверьте логи."
            })
            
    except Exception as e:
        logger.error(f"Ошибка в send-now: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Исключение: {str(e)}"
        })

@app.route('/test-channel')
def test_channel():
    """Тестирование подключения к каналу"""
    test_message = f"✅ ТЕСТ: Канал подключен! ID: {Config.TELEGRAM_CHANNEL}\nВремя: {datetime.now().strftime('%H:%M:%S')}"
    
    success = elite_channel.send_to_telegram(test_message)
    
    return jsonify({
        "status": "success" if success else "error",
        "message": "Тестовое сообщение отправлено" if success else "Ошибка отправки",
        "channel_id": Config.TELEGRAM_CHANNEL,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/channel-info')
def channel_info():
    """Информация о канале"""
    return jsonify({
        "channel_id": Config.TELEGRAM_CHANNEL,
        "channel_username": "@ppsupershef",
        "bot_token_preview": Config.TELEGRAM_BOT_TOKEN[:10] + "..." if Config.TELEGRAM_BOT_TOKEN else "Not set",
        "environment": "production" if os.getenv('PRODUCTION') else "development"
    })

# Новые маршруты для диагностики
@app.route('/force-fix')
def force_fix():
    """Принудительная отправка с правильным ID"""
    # Принудительно обновляем ID
    elite_channel.channel = '-100362423055'
    
    test_message = f"🔧 ПРИНУДИТЕЛЬНЫЙ ТЕСТ\nID: {elite_channel.channel}\nВремя: {datetime.now().strftime('%H:%M:%S')}"
    
    success = elite_channel.send_to_telegram(test_message)
    
    return jsonify({
        "status": "success" if success else "error",
        "channel_used": elite_channel.channel,
        "message": "Тест отправлен с правильным ID канала" if success else "Ошибка отправки"
    })

@app.route('/check-connection')
def check_connection():
    """Проверка соединения с Telegram API"""
    import requests
    
    bot_token = Config.TELEGRAM_BOT_TOKEN
    channel_id = Config.TELEGRAM_CHANNEL
    
    try:
        # Проверяем бота
        bot_url = f"https://api.telegram.org/bot{bot_token}/getMe"
        bot_response = requests.get(bot_url, timeout=10).json()
        
        # Проверяем канал
        chat_url = f"https://api.telegram.org/bot{bot_token}/getChat"
        chat_response = requests.post(chat_url, json={'chat_id': channel_id}, timeout=10).json()
        
        return jsonify({
            "bot_status": "valid" if bot_response.get('ok') else "invalid",
            "channel_status": "accessible" if chat_response.get('ok') else "inaccessible",
            "channel_id": channel_id,
            "bot_username": bot_response.get('result', {}).get('username') if bot_response.get('ok') else None,
            "channel_title": chat_response.get('result', {}).get('title') if chat_response.get('ok') else None
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    logger.info(f"🚀 Запуск приложения с каналом ID: {Config.TELEGRAM_CHANNEL}")
    app.run(host='0.0.0.0', port=10000, debug=True)
