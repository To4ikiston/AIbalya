import os
import logging
from flask import Flask, request, jsonify
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler, Filters

# Настройка логирования
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Получаем токен бота из переменной окружения BOT_TOKEN, установленной в Render
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=0, use_context=True)

# Локальное хранение контекста (для простоты используем словарь)
contexts = {}

# Определение вариантов мозгового штурма с именами и промтами
BRAINSTORM_ROLES = {
    "gradis": {
         "name": "ГРАДИС",
         "prompt": ("Градис анализирует диалог как опытный профессионал, предлагая проверенные решения. "
                    "Пишет так, будто это коллега, а не алгоритм. Пример: 'Вместо Vue.js советую начать с React — "
                    "больше вакансий для джунов. Проверено на проектах в 2023–2024 гг.'")
    },
    "novaris": {
         "name": "НОВАРИС",
         "prompt": ("Новарис мыслит за пределами шаблонов, генерируя смелые, но реализуемые идеи. Не скрывает свою ИИ-природу, "
                    "подчеркивает инновации. Пример: 'Предлагаю внедрить нейросеть для анализа CV — мой прототип сократит время найма на 40%. "
                    "Давайте обсудим архитектуру?'")
    },
    "aksios": {
         "name": "АКСИОС",
         "prompt": ("Аксиос оценивает идеи через призму эффективности, указывает на слабые места и предлагает улучшения. "
                    "Строг, но конструктивен. Пример: 'Ваш план изучения Python за месяц нереалистичен. Оптимизирую: 1) Сначала основы (3 недели), 2) Проекты на Flask (остальное время).'")
    },
    "inspectra": {
         "name": "ИНСПЕКТРА",
         "prompt": ("Инспектра фокусируется на генерации идей без анализа прошлого. Формулирует предложения тезисно, "
                    "провоцируя мозговой штурм. Пример: 'Варианты монетизации: 1) Партнерка с Coursera, 2) Telegram-курс «Python за 7 дней», 3) Консультации по карьере в IT.'")
    }
}

# Команда /start
def start(update, context):
    update.message.reply_text("Привет! Я ВАЛТОР — ваш бот-помощник. Используйте /help для получения списка команд.")

# Команда /help с подробным описанием
def help_command(update, context):
    help_text = (
        "Список команд:\n"
        "/start - Запуск бота\n"
        "/help - Справка по командам\n"
        "/ask <вопрос> - Задать вопрос. Пример: /ask Как улучшить проект?\n"
        "/context - Показать последние сообщения, сохраненные в контексте\n"
        "/context setlimit <число> - Установить лимит сообщений для контекста. Пример: /context setlimit 30\n"
        "/context remove <номер> - Удалить конкретное сообщение из контекста. Пример: /context remove 2\n"
        "/clear - Очистить контекст\n"
        "/brainstorm - Запустить мозговой штурм с выбором варианта\n"
        "/summarize - Подвести итог беседы (будет добавлено позже)\n"
        "\nТакже если вы упомянете @VALTOR, я отвечу автоматически!"
    )
    update.message.reply_text(help_text)

# Команда /ask
def ask(update, context):
    chat_id = update.message.chat_id
    user_text = update.message.text.replace("/ask", "").strip()
    if not user_text:
        update.message.reply_text("Пожалуйста, введите вопрос после /ask")
        return
    # Здесь можно добавить вызов внешнего API с использованием контекста
    update.message.reply_text(f"Ответ на ваш вопрос: {user_text}")

# Команда /context — показать контекст
def show_context(update, context):
    chat_id = update.message.chat_id
    msgs = contexts.get(chat_id, [])
    if msgs:
        text = "\n".join(f"{i+1}. {msg}" for i, msg in enumerate(msgs))
    else:
        text = "Контекст пуст."
    update.message.reply_text(text)

# Команда /clear — очистить контекст
def clear_context(update, context):
    chat_id = update.message.chat_id
    contexts[chat_id] = []
    update.message.reply_text("Контекст очищен.")

# Команда /brainstorm — вывод inline-кнопок для выбора варианта мозгового штурма
def brainstorm(update, context):
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="brainstorm_gradis")],
        [InlineKeyboardButton("НОВАРИС", callback_data="brainstorm_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="brainstorm_aksios")],
        [InlineKeyboardButton("ИНСПЕКТРА", callback_data="brainstorm_inspectra")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выберите вариант мозгового штурма:", reply_markup=reply_markup)

# Обработчик нажатия inline-кнопок
def button_callback(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    if data.startswith("brainstorm_"):
        role_key = data.replace("brainstorm_", "")
        role = BRAINSTORM_ROLES.get(role_key)
        if role:
            chat_id = query.message.chat_id
            msgs = contexts.get(chat_id, [])
            context_text = "\n".join(msgs[-5:]) if msgs else "Нет контекста."
            response = f"{role['name']} отвечает:\nПромт: {role['prompt']}\nКонтекст:\n{context_text}"
            query.edit_message_text(text=response)
        else:
            query.edit_message_text(text="Ошибка: роль не найдена.")

# Обработчик всех обычных сообщений — сохраняем в контексте и проверяем упоминание бота
def echo(update, context):
    chat_id = update.message.chat_id
    text = update.message.text
    if chat_id not in contexts:
        contexts[chat_id] = []
    contexts[chat_id].append(text)
    if "ВАЛТОР" in text.upper() or "@VALTOR" in text.upper():
        update.message.reply_text("Вы позвали меня? Используйте /ask для вопросов или /brainstorm для мозгового штурма.")

# Регистрируем обработчики команд и сообщений
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("ask", ask))
dispatcher.add_handler(CommandHandler("context", show_context))
dispatcher.add_handler(CommandHandler("clear", clear_context))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm))
dispatcher.add_handler(CallbackQueryHandler(button_callback))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))

# Точка входа для вебхуков. URL будет вида: https://<RENDER_URL>/<BOT_TOKEN>
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return jsonify({"status": "ok"})

# Точка проверки работы сервера
@app.route("/")
def index():
    return "Бот ВАЛТОР работает!"

if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 5000)))
