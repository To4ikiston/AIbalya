import os
import logging
from quart import Quart, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Quart(__name__)

# Конфигурация из переменных окружения
BOT_TOKEN = os.environ["BOT_TOKEN"]
SECRET_TOKEN = os.environ["SECRET_TOKEN"]

# Инициализация приложения бота
application = Application.builder().token(BOT_TOKEN).build()

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Бот активирован! Используйте /help для списка команд")

# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 Доступные команды:\n"
        "/start - Запустить бота\n"
        "/help - Показать это сообщение"
    )
    await update.message.reply_text(help_text)

# Вебхук для Telegram
@app.post('/webhook')
async def webhook():
    try:
        # Проверка секретного токена
        if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET_TOKEN:
            logger.error("Неверный секретный токен")
            return "Unauthorized", 401

        # Получение и обработка обновления
        json_data = await request.get_json()
        update = Update.de_json(json_data, application.bot)
        
        # Инициализация и обработка
        await application.initialize()
        await application.process_update(update)
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        return "Internal Server Error", 500

# Health check эндпоинт
@app.get('/')
async def health_check():
    return "🤖 Бот в активном режиме", 200

# Регистрация обработчиков команд
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))
