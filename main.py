import os
from quart import Quart, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

app = Quart(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")

# Инициализация бота
application = Application.builder().token(BOT_TOKEN).build()

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Бот запущен!")

# Вебхук
@app.route("/webhook", methods=["POST"])
async def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
        return "Unauthorized", 401
    
    json_data = await request.get_json()
    update = Update.de_json(json_data, application.bot)
    await application.process_update(update)
    return "OK", 200

# Health check
@app.route("/")
async def health_check():
    return "🤖 Бот активен", 200

# Регистрация обработчиков
application.add_handler(CommandHandler("start", start))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))
