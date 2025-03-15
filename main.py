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

#############################################################################
# 0. Общая настройка
#############################################################################

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "NO_TOKEN_PROVIDED")
bot = Bot(token=BOT_TOKEN)

# Создаём Dispatcher с несколькими потоками
dispatcher = Dispatcher(bot, None, workers=2, use_context=True)

# Хранилище контекста:
# contexts[chat_id] = {
#   "messages": [строки],  # список сообщений
#   "limit": 30            # лимит для хранения
# }
contexts = {}

#############################################################################
# 1. Заглушки для API (DeepSeek и т.п.)
#############################################################################

def call_deepseek_api(question: str, context_messages: list) -> str:
    """
    Здесь будет реальный вызов DeepSeek, когда у вас появится ключ.
    Пока заглушка просто возвращает вопрос + последние 5 сообщений контекста.
    """
    last5 = "\n".join(context_messages[-5:])
    return (
        f"=== ЗАГЛУШКА DeepSeek ===\n"
        f"Вопрос: {question}\n\n"
        f"Последние 5 сообщений:\n{last5}"
    )

def summarize_context(context_messages: list) -> str:
    """
    Заглушка для команды /summarize.
    Реально вы могли бы вызывать DeepSeek или другую модель для суммирования.
    Пока делаем примитив.
    """
    if not context_messages:
        return "Контекст пуст, нечего суммировать."
    # Допустим, просто берём 5 последних и выдаём "итоги"
    last5 = context_messages[-5:]
    summary = "\n".join(last5)
    return (
        "=== ЗАГЛУШКА ИТОГОВ ===\n"
        "Вот 5 последних сообщений:\n"
        f"{summary}\n\n"
        "Допустим, это краткий обзор."
    )

#############################################################################
# 2. Вспомогательные функции для работы с контекстом
#############################################################################

def get_chat_context(chat_id: int) -> dict:
    """Возвращает структуру контекста для данного chat_id."""
    if chat_id not in contexts:
        contexts[chat_id] = {
            "messages": [],
            "limit": 30,  # по умолчанию храним 30 последних
        }
    return contexts[chat_id]

def add_message_to_context(chat_id: int, message: str):
    ctx = get_chat_context(chat_id)
    ctx["messages"].append(message)
    # Если превысили лимит — обрезаем начало
    limit = ctx["limit"]
    if len(ctx["messages"]) > limit:
        ctx["messages"] = ctx["messages"][-limit:]

#############################################################################
# 3. Обработчики команд
#############################################################################

def start_command(update, context):
    logging.info("Команда /start вызвана")
    update.message.reply_text(
        "Привет! Я ВАЛТОР — ваш бот-помощник. Используйте /help для списка команд."
    )

def help_command(update, context):
    logging.info("Команда /help вызвана")
    text = (
        "Доступные команды:\n"
        "/start — приветствие\n"
        "/help — эта справка\n"
        "/ask <вопрос> — задать вопрос (заглушка для DeepSeek)\n"
        "/summarize — подвести итоги последних сообщений\n"
        "/context — показать весь контекст (по умолчанию, до 30 сообщений)\n"
        "/context setlimit <число> — изменить лимит хранения\n"
        "/context remove <номер> — удалить сообщение по индексу\n"
        "/clear — очистить контекст\n"
        "/brainstorm — запустить мозговой штурм (ГРАДИС, НОВАРИС, АКСИОС, ИНСПЕКТРА)\n"
    )
    update.message.reply_text(text)

def ask_command(update, context):
    logging.info("Команда /ask вызвана")
    chat_id = update.message.chat_id
    # Текст вопроса
    user_text = update.message.text.replace("/ask", "", 1).strip()
    if not user_text:
        update.message.reply_text("Пожалуйста, введите вопрос после /ask.")
        return

    ctx = get_chat_context(chat_id)
    messages = ctx["messages"]

    # Вызываем заглушку DeepSeek
    answer = call_deepseek_api(user_text, messages)
    update.message.reply_text(answer)

def summarize_command(update, context):
    logging.info("Команда /summarize вызвана")
    chat_id = update.message.chat_id
    ctx = get_chat_context(chat_id)
    messages = ctx["messages"]
    answer = summarize_context(messages)
    update.message.reply_text(answer)

def context_command(update, context):
    """
    /context
    /context setlimit <число>
    /context remove <номер>
    """
    logging.info("Команда /context вызвана")
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    parts = text.split()
    if len(parts) == 1:
        # Просто показать контекст
        show_full_context(update, chat_id)
        return

    # Есть подкоманда
    subcmd = parts[1]
    if subcmd == "setlimit":
        if len(parts) < 3:
            update.message.reply_text("Формат: /context setlimit <число>")
            return
        try:
            limit = int(parts[2])
            ctx = get_chat_context(chat_id)
            ctx["limit"] = limit
            # Обрежем, если уже превышаем
            if len(ctx["messages"]) > limit:
                ctx["messages"] = ctx["messages"][-limit:]
            update.message.reply_text(f"Лимит контекста изменён на {limit} сообщений.")
        except ValueError:
            update.message.reply_text("Неверный формат числа.")
    elif subcmd == "remove":
        if len(parts) < 3:
            update.message.reply_text("Формат: /context remove <номер>")
            return
        try:
            index_str = parts[2]
            index_to_remove = int(index_str)
            ctx = get_chat_context(chat_id)
            if 1 <= index_to_remove <= len(ctx["messages"]):
                removed_msg = ctx["messages"].pop(index_to_remove - 1)
                update.message.reply_text(f"Удалено: {removed_msg}")
            else:
                update.message.reply_text("Номер сообщения вне диапазона.")
        except ValueError:
            update.message.reply_text("Неверный формат номера.")
    else:
        update.message.reply_text("Неизвестная подкоманда для /context.")

def show_full_context(update, chat_id: int):
    """Помощник для вывода полного списка сообщений."""
    ctx = get_chat_context(chat_id)
    messages = ctx["messages"]
    if not messages:
        update.message.reply_text("Контекст пуст.")
        return
    lines = []
    for i, msg in enumerate(messages, start=1):
        lines.append(f"{i}. {msg}")
    text = "\n".join(lines)
    update.message.reply_text(text)

def clear_command(update, context):
    logging.info("Команда /clear вызвана")
    chat_id = update.message.chat_id
    contexts[chat_id] = {
        "messages": [],
        "limit": 30
    }
    update.message.reply_text("Контекст очищен.")

#############################################################################
# 4. Мозговой штурм (brainstorm)
#############################################################################

BRAINSTORM_ROLES = {
    "gradis": {
        "name": "ГРАДИС",
        "prompt": "Градис анализирует диалог как опытный профессионал..."
    },
    "novaris": {
        "name": "НОВАРИС",
        "prompt": "Новарис мыслит за пределами шаблонов..."
    },
    "aksios": {
        "name": "АКСИОС",
        "prompt": "Аксиос оценивает идеи через призму эффективности..."
    },
    "inspectra": {
        "name": "ИНСПЕКТРА",
        "prompt": "Инспектра фокусируется на генерации идей без анализа прошлого..."
    }
}

def brainstorm_command(update, context):
    logging.info("Команда /brainstorm вызвана")
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="brainstorm_gradis")],
        [InlineKeyboardButton("НОВАРИС", callback_data="brainstorm_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="brainstorm_aksios")],
        [InlineKeyboardButton("ИНСПЕКТРА", callback_data="brainstorm_inspectra")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выберите вариант мозгового штурма:", reply_markup=markup)

def button_callback(update, context):
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
        ctx = get_chat_context(chat_id)
        last_msgs = ctx["messages"][-5:]
        text = (
            f"{role_info['name']} отвечает!\n"
            f"Промт: {role_info['prompt']}\n\n"
            f"Последние 5 сообщений:\n{'\n'.join(last_msgs)}"
        )
        query.edit_message_text(text)

#############################################################################
# 5. Обработчик обычных сообщений (не команд)
#############################################################################

def text_handler(update, context):
    chat_id = update.message.chat_id
    text = update.message.text
    logging.info(f"Обычный текст от пользователя: {text}")
    # Сохраняем в контексте
    add_message_to_context(chat_id, text)

    # Для наглядности бот отвечает, что добавил сообщение
    update.message.reply_text("Сообщение добавлено в контекст.")

#############################################################################
# 6. Регистрация команд и запуск
#############################################################################

# Регистрируем команды
dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("ask", ask_command))
dispatcher.add_handler(CommandHandler("summarize", summarize_command))
dispatcher.add_handler(CommandHandler("context", context_command))
dispatcher.add_handler(CommandHandler("clear", clear_command))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm_command))
dispatcher.add_handler(CallbackQueryHandler(button_callback))

# Регистрируем обработчик обычного текста
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))

@app.route("/")
def index():
    return "ВАЛТОР запущен и работает!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update_json = request.get_json(force=True)
    logging.info("Получено обновление: %s", update_json)
    update_obj = Update.de_json(update_json, bot)
    dispatcher.process_update(update_obj)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
