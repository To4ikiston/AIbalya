import os
from flask import Flask, request, jsonify
from telegram import Update, Bot
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler, Filters
import logging

from app.config import BOT_TOKEN, APP_URL, SECRET_TOKEN
from app.handlers.start import start_command
from app.handlers.help import help_command
from app.handlers.ask import ask_command
from app.handlers.context import context_command  # пример, если разбили на модуль
from app.handlers.brainstorm import brainstorm_command
from app.handlers.active import active_command
from app.handlers.dismiss import dismiss_command
from app.handlers.stats import stats_command
from app.handlers.summarize import summarize_command
from app.handlers.text_handler import text_message_handler
from app.handlers.clear import clear_command

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=4, use_context=True)

# Регистрируем обработчики
dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("ask", ask_command))
dispatcher.add_handler(CommandHandler("context", context_command))
dispatcher.add_handler(CommandHandler("clear", clear_command))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm_command))
dispatcher.add_handler(CommandHandler("active", active_command))
dispatcher.add_handler(CommandHandler("dismiss", dismiss_command))
dispatcher.add_handler(CommandHandler("stats", stats_command))
dispatcher.add_handler(CommandHandler("summarize", summarize_command))
dispatcher.add_handler(CallbackQueryHandler(lambda u, c: None))  # Здесь подключите button_callback
dispatcher.add_handler(MessageHandler(Filters.text, text_message_handler))

@app.route("/")
def index():
    return "Император охраняет Империум!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook_endpoint():
    update_json = request.get_json(force=True)
    update_obj = Update.de_json(update_json, bot)
    dispatcher.process_update(update_obj)
    return jsonify({"ok": True})

if __name__ == "__main__":
    # Установка вебхука
    if APP_URL:
        webhook_url = f"{APP_URL}/{BOT_TOKEN}"
        bot.set_webhook(url=webhook_url, secret_token=SECRET_TOKEN)
        logger.info(f"Webhook установлен: {webhook_url}")
    else:
        logger.warning("APP_URL не задан.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
