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

# Настройка логирования для отладки
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Считываем токен из переменной окружения BOT_TOKEN (Render должен его задать)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)

# Создаем Dispatcher с workers=2 (чтобы обработка обновлений проходила в потоках)
dispatcher = Dispatcher(bot, None, workers=2, use_context=True)

# Локальное хранилище контекста для каждого чата
contexts = {}

# Определение вариантов мозгового штурма с промтами
BRAINSTORM_ROLES = {
    "gradis": {
        "name": "ГРАДИС",
        "prompt": (
            "Градис анализирует диалог как опытный профессионал, предлагая проверенные решения. "
            "Пишет так, будто это коллега, а не алгоритм. Пример: 'Вместо Vue.js советую начать с React — "
            "больше вакансий для джунов. Проверено на проектах в 2023–2024 гг.'"
        ),
    },
    "novaris": {
        "name": "НОВАРИС",
        "prompt": (
            "Новарис мыслит за пределами шаблонов, генерируя смелые, но реализуемые идеи. "
            "Не скрывает свою ИИ-природу, подчеркивает инновации. Пример: 'Предлагаю внедрить нейросеть для анализа CV — "
            "мой прототип сократит время найма на 40%. Давайте обсудим архитектуру?'"
        ),
    },
    "aksios": {
        "name": "АКСИОС",
        "prompt": (
            "Аксиос оценивает идеи через призму эффективности, указывает на слабые места и предлагает улучшения. "
            "Строг, но конструктивен. Пример: 'Ваш план изучения Python за месяц нереалистичен. "
            "Оптимизирую: 1) Сначала основы (3 недели), 2) Проекты на Flask (остальное время).'"
        ),
    },
    "inspectra": {
        "name": "ИНСПЕКТРА",
        "prompt": (
            "Инспектра фокусируется на генерации идей без анализа прошлого. Формулирует предложения тезисно, "
            "провоцируя мозговой штурм. Пример: 'Варианты монетизации: 1) Партнерка с Coursera, 2) Telegram-курс «Python за 7 дней», 3) Консультации по карьере в IT.'"
        ),
    },
}


# --- Обработчики команд Telegram ---

def start(update, context):
    update.message.reply_text(
        "Привет! Я ВАЛТОР — ваш бот-помощник. Используйте /help для получения списка команд."
    )


def help_command(update, context):
    help_text = (
        "Список команд:\n"
        "/start — Запуск бота\n"
        "/help — Справка по командам\n"
        "/ask <вопрос> — Задать вопрос. Пример: /ask Как улучшить проект?\n"
        "/context — Показать последние сообщения контекста\n"
        "/clear — Очистить контекст\n"
        "/brainstorm — Запустить мозговой штурм (выбор варианта)\n"
        "\nТакже, если вы упомянете 'ВАЛТОР' или '@VALTOR', я отвечу автоматически."
    )
    update.message.reply_text(help_text)


def ask(update, context):
    chat_id = update.message.chat_id
    user_text = update.message.text.replace("/ask", "").strip()
    if not user_text:
        update.message.reply_text("Пожалуйста, введите вопрос после /ask")
        return
    update.message.reply_text(f"Ответ на ваш вопрос: {user_text}")


def show_context(update, context):
    chat_id = update.message.chat_id
    msgs = contexts.get(chat_id, [])
    if msgs:
        text = "\n".join(f"{i+1}. {msg}" for i, msg in enumerate(msgs))
    else:
        text = "Контекст пуст."
    update.message.reply_text(text)


def clear_context(update, context):
    chat_id = update.message.chat_id
    contexts[chat_id] = []
    update.message.reply_text("Контекст очищен.")


def brainstorm(update, context):
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="brainstorm_gradis")],
        [InlineKeyboardButton("НОВАРИС", callback_data="brainstorm_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="brainstorm_aksios")],
        [InlineKeyboardButton("ИНСПЕКТРА", callback_data="brainstorm_inspectra")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выберите вариант мозгового штурма:", reply_markup=reply_markup)


def button_callback(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    logging.info("Inline-кнопка нажата: %s", data)
    if data.startswith("brainstorm_"):
        role_key = data.replace("brainstorm_", "")
        role = BRAINSTORM_ROLES.get(role_key)
        if role:
            chat_id = query.message.chat_id
            msgs = contexts.get(chat_id, [])
            context_text = "\n".join(msgs[-5:]) if msgs else "Нет контекста."
            response = (
                f"{role['name']} отвечает:\n"
                f"Промт: {role['prompt']}\n"
                f"Контекст:\n{context_text}"
            )
            query.edit_message_text(response)
        else:
            query.edit_message_text("Ошибка: роль не найдена.")


def echo(update, context):
    chat_id = update.message.chat_id
    text = update.message.text
    if chat_id not in contexts:
        contexts[chat_id] = []
    contexts[chat_id].append(text)
    if "ВАЛТОР" in text.upper() or "@VALTOR" in text.upper():
        update.message.reply_text(
            "Вы позвали меня? Используйте /ask для вопросов или /brainstorm для мозгового штурма."
        )


# --- Регистрация обработчиков ---
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("ask", ask))
dispatcher.add_handler(CommandHandler("context", show_context))
dispatcher.add_handler(CommandHandler("clear", clear_context))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm))
dispatcher.add_handler(CallbackQueryHandler(button_callback))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))


# --- Flask endpoints ---

@app.route("/")  # Проверка работы сервера
def index():
    return "Бот ВАЛТОР работает!"


# Endpoint для вебхука: URL будет https://<RENDER_URL>/<BOT_TOKEN>
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update_json = request.get_json(force=True)
    logging.info("Получено обновление: %s", update_json)
    update = Update.de_json(update_json, bot)
    dispatcher.process_update(update)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
