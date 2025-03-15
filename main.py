import os
import logging
from flask import Flask, request, jsonify
from telegram import Bot, Update
from telegram.ext import (
    Dispatcher,
    CommandHandler,
    MessageHandler,
    Filters
)

# Включаем логирование, чтобы в логах Render видеть, что происходит
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Берём токен бота из переменной окружения BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN", "NO_TOKEN_PROVIDED")
bot = Bot(token=BOT_TOKEN)

# Создаём Dispatcher. workers=2, чтобы был хотя бы 1 поток для асинхронной обработки
dispatcher = Dispatcher(bot, None, workers=2, use_context=True)

# --- Обработчики команд ---
def start_command(update, context):
    logging.info("/start вызван")  # Логируем
    update.message.reply_text("Привет! Я тестовый бот на Render. Используйте /help, чтобы увидеть команды.")

def help_command(update, context):
    logging.info("/help вызван")
    help_text = (
        "Доступные команды:\n"
        "/start — Запустить бота\n"
        "/help — Справка\n"
        "/echo <текст> — Бот повторит ваш текст\n"
    )
    update.message.reply_text(help_text)

def echo_command(update, context):
    logging.info("/echo вызван")
    user_text = update.message.text
    # /echo занимает часть строки, убираем её
    text_to_echo = user_text.replace("/echo", "", 1).strip()
    if not text_to_echo:
        update.message.reply_text("После /echo напишите любой текст, и я повторю его.")
        return
    update.message.reply_text(f"Вы сказали: {text_to_echo}")

# --- Обработчик любого текста (не команды) ---
def text_handler(update, context):
    # Просто отвечаем: "Вы сказали: ..."
    user_text = update.message.text
    update.message.reply_text(f"Вы сказали: {user_text}")

# Регистрируем обработчики в Dispatcher
dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("echo", echo_command))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))

# --- Flask endpoints ---

@app.route("/")
def index():
    return "Бот запущен. Всё работает!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    """
    Эта функция вызывается, когда Telegram шлёт обновление (update) на наш вебхук.
    """
    update_json = request.get_json(force=True)
    logging.info("Получено обновление: %s", update_json)

    update_obj = Update.de_json(update_json, bot)
    dispatcher.process_update(update_obj)
    return jsonify({"ok": True})

if __name__ == "__main__":
    # Локальный запуск (для отладки) - не нужен на Render, но пригодится если тестируете локально.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
