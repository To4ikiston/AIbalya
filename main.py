import os
import logging
from flask import Flask, request, jsonify
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Dispatcher,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters
)

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Токен бота из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN", "NO_TOKEN_PROVIDED")
bot = Bot(token=BOT_TOKEN)

# Если в будущем решите хранить URL приложения в переменной окружения:
# APP_URL = os.getenv("APP_URL", "https://aibalya-1.onrender.com")

# Создаем Dispatcher с несколькими воркерами
dispatcher = Dispatcher(bot, None, workers=2, use_context=True)

#############################################################################
# 1. Заготовка функции для будущего вызова DeepSeek (сейчас — заглушка)
#############################################################################

def call_deepseek_api(question: str, context_messages: list) -> str:
    """
    Заглушка. Позже здесь будет реальный вызов DeepSeek, например:
    
    import requests
    
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    response = requests.post(
        "https://api.deepseek.ai/v1/ask",
        json={
            "question": question,
            "context": context_messages
        },
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    )
    data = response.json()
    return data["answer"]
    
    Пока возвращаем примерный текст:
    """
    joined_context = "\n".join(context_messages[-5:])  # последние 5 сообщений
    return (
        f"Это заглушка для DeepSeek. Ваш вопрос: {question}\n"
        f"Контекст (последние 5 сообщений):\n{joined_context}"
    )

#############################################################################
# 2. Локальное хранилище контекста для каждого чата
#############################################################################

# Например, словарь: {(chat_id, thread_id?): [строки сообщений]}
# Для простоты — пока только по chat_id, без учёта thread_id
contexts = {}

def get_context(chat_id: int) -> list:
    """Возвращает список сообщений для данного чата."""
    if chat_id not in contexts:
        contexts[chat_id] = []
    return contexts[chat_id]

def add_to_context(chat_id: int, text: str):
    """Добавляет текст сообщения в контекст."""
    if chat_id not in contexts:
        contexts[chat_id] = []
    contexts[chat_id].append(text)
    # Можно ограничить размер, например, 50 сообщений:
    if len(contexts[chat_id]) > 50:
        contexts[chat_id] = contexts[chat_id][-50:]


#############################################################################
# 3. Обработчики команд
#############################################################################

def start_command(update, context):
    logging.info("Обработчик /start вызван")
    update.message.reply_text(
        "Привет! Я ВАЛТОР — ваш бот-помощник. Используйте /help для списка команд."
    )

def help_command(update, context):
    logging.info("Обработчик /help вызван")
    help_text = (
        "Список команд:\n"
        "/start — приветственное сообщение\n"
        "/help — справка по командам\n"
        "/ask <вопрос> — задать вопрос (в будущем к DeepSeek)\n"
        "/context — показать текущий контекст\n"
        "/context remove <номер> — удалить одно сообщение по индексу\n"
        "/clear — очистить весь контекст\n"
        "/brainstorm — мозговой штурм (выбрать ГРАДИС, НОВАРИС и т.д.)\n"
    )
    update.message.reply_text(help_text)

def ask_command(update, context):
    logging.info("Обработчик /ask вызван")
    chat_id = update.message.chat_id

    # Текст, идущий после "/ask"
    user_text = update.message.text.replace("/ask", "", 1).strip()
    if not user_text:
        update.message.reply_text("Пожалуйста, введите вопрос после /ask.")
        return

    # Берём контекст
    current_context = get_context(chat_id)
    # Вызываем заглушку DeepSeek
    answer = call_deepseek_api(user_text, current_context)
    update.message.reply_text(answer)

def show_context_command(update, context):
    logging.info("Обработчик /context вызван")
    chat_id = update.message.chat_id
    msgs = get_context(chat_id)
    if not msgs:
        update.message.reply_text("Контекст пуст.")
        return
    # Показать сообщения, пронумеровав
    lines = []
    for i, msg in enumerate(msgs, start=1):
        lines.append(f"{i}. {msg}")
    text = "\n".join(lines)
    update.message.reply_text(text)

def context_remove_command(update, context):
    """Пример: /context remove 3"""
    chat_id = update.message.chat_id
    current_context = get_context(chat_id)

    parts = update.message.text.split()
    if len(parts) < 3:
        update.message.reply_text("Формат: /context remove <номер>")
        return
    try:
        index_to_remove = int(parts[2])  # "3"
        if 1 <= index_to_remove <= len(current_context):
            removed_msg = current_context.pop(index_to_remove - 1)
            update.message.reply_text(f"Удалено: {removed_msg}")
        else:
            update.message.reply_text("Номер сообщения вне диапазона.")
    except ValueError:
        update.message.reply_text("Неверный формат номера.")

def clear_command(update, context):
    logging.info("Обработчик /clear вызван")
    chat_id = update.message.chat_id
    contexts[chat_id] = []
    update.message.reply_text("Контекст очищен.")

#############################################################################
# 4. Мозговой штурм (inline-кнопки)
#############################################################################

BRAINSTORM_ROLES = {
    "gradis": {
        "name": "ГРАДИС",
        "prompt": "Градис анализирует диалог как опытный профессионал..."
    },
    "novaris": {
        "name": "НОВАРИС",
        "prompt": "Новарис мыслит за пределами шаблонов, генерируя..."
    },
    "aksios": {
        "name": "АКСИОС",
        "prompt": "Аксиос оценивает идеи через призму эффективности..."
    },
    "inspectra": {
        "name": "ИНСПЕКТРА",
        "prompt": "Инспектра фокусируется на генерации идей без анализа..."
    },
}

def brainstorm_command(update, context):
    logging.info("Обработчик /brainstorm вызван")
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="brainstorm_gradis")],
        [InlineKeyboardButton("НОВАРИС", callback_data="brainstorm_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="brainstorm_aksios")],
        [InlineKeyboardButton("ИНСПЕКТРА", callback_data="brainstorm_inspectra")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выберите вариант мозгового штурма:", reply_markup=reply_markup)

def button_callback(update, context):
    """Обработчик нажатий inline-кнопок (callback_data)."""
    query = update.callback_query
    query.answer()
    data = query.data
    logging.info(f"Нажата inline-кнопка: {data}")

    if data.startswith("brainstorm_"):
        role_key = data.replace("brainstorm_", "")
        role_info = BRAINSTORM_ROLES.get(role_key)
        if not role_info:
            query.edit_message_text("Ошибка: роль не найдена.")
            return
        chat_id = query.message.chat_id
        current_context = get_context(chat_id)
        last_msgs = "\n".join(current_context[-5:])
        # Тут тоже можно вызвать `call_deepseek_api` или что-то подобное
        answer = (
            f"{role_info['name']} отвечает!\n"
            f"Промт: {role_info['prompt']}\n\n"
            f"Последние 5 сообщений:\n{last_msgs}"
        )
        query.edit_message_text(answer)

#############################################################################
# 5. Общий обработчик любых текстовых сообщений (не команд)
#############################################################################

def text_handler(update, context):
    chat_id = update.message.chat_id
    text = update.message.text
    add_to_context(chat_id, text)

    # Простая реакция, чтобы видно было, что бот "слышит"
    update.message.reply_text(f"Добавлено в контекст: {text}")


#############################################################################
# 6. Регистрируем все обработчики в Dispatcher
#############################################################################

dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("ask", ask_command))

# /context (показать) и /context remove <n> (удалить)
dispatcher.add_handler(CommandHandler("context", show_context_command))
dispatcher.add_handler(CommandHandler("clear", clear_command))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm_command))
dispatcher.add_handler(CallbackQueryHandler(button_callback))

# Специальный обработчик "context remove ...", чтобы не делать отдельную команду?
# Можно оставить всё в одной, как сейчас.

# Любые тексты (не команды) - добавляем в контекст
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))

#############################################################################
# 7. Flask endpoints
#############################################################################

@app.route("/")
def index():
    return "ВАЛТОР запущен и работает!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    """Точка входа для обновлений от Telegram."""
    update_json = request.get_json(force=True)
    logging.info("Получено обновление: %s", update_json)
    update_obj = Update.de_json(update_json, bot)
    dispatcher.process_update(update_obj)
    return jsonify({"ok": True})

if __name__ == "__main__":
    # Для локального запуска
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
