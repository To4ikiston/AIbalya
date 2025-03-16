import os
import logging
from flask import Flask, request, jsonify
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
)
from telegram.ext import (
    Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler, Filters
)

# Настройка логирования
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Получаем токен бота из переменной окружения BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN", "NO_TOKEN_PROVIDED")
bot = Bot(token=BOT_TOKEN)

# Создаем Dispatcher с workers=2 для асинхронной обработки
dispatcher = Dispatcher(bot, None, workers=2, use_context=True)

#############################################################################
# 1. Глобальные структуры
#############################################################################

# Хранение контекста: contexts[chat_id] = [сообщения]
contexts = {}

def get_context(chat_id: int) -> list:
    if chat_id not in contexts:
        contexts[chat_id] = []
    return contexts[chat_id]

def add_to_context(chat_id: int, text: str):
    ctx = get_context(chat_id)
    ctx.append(text)
    # Ограничим до 100 сообщений
    if len(ctx) > 100:
        contexts[chat_id] = ctx[-100:]

# Хранение активного персонажа: active_sessions[chat_id] = character_id (например, "gradis")
active_sessions = {}

#############################################################################
# 2. Заглушки для вызова API и суммаризации
#############################################################################

def call_deepseek_api(character_name: str, prompt: str, context_messages: list) -> str:
    """
    Заглушка для вызова DeepSeek. Позже сюда будет реальный HTTP-запрос.
    """
    last30 = "\n".join(context_messages[-30:]) if context_messages else "Нет сообщений."
    return (
        f"=== Ответ от {character_name} ===\n"
        f"Промт: {prompt}\n\n"
        f"Контекст (последние 30 сообщений):\n{last30}\n\n"
        f"(Это заглушка для DeepSeek)"
    )

def summarize_context(character_name: str, prompt: str, context_messages: list) -> str:
    """
    Заглушка для финальной суммаризации перед прощанием.
    """
    last30 = "\n".join(context_messages[-30:]) if context_messages else "Нет сообщений."
    return (
        f"=== Финальный итог от {character_name} ===\n"
        f"Промт: {prompt}\n\n"
        f"Итоговая сводка (последние 30 сообщений):\n{last30}\n\n"
        f"(Это заглушка для финальной суммаризации)"
    )

#############################################################################
# 3. Определение персонажей для мозгового штурма (Warhammer-стиль)
#############################################################################

# Словарь персонажей: ключ — id, значение — данные
WARHAMMER_CHARACTERS = {
    "gradis": {
        "display_name": "ГРАДИС — Архивариус Знания (Эксперт-человек)",
        "gif_url": "https://media.giphy.com/media/3o7abB06u9bNzA8lu8/giphy.gif",
        "description": (
            "Хранитель догматов Омниссиаха, превращающий опыт в алгоритмы.\n"
            "Боевой стиль: атакует хаотичные идеи логическими вирусами.\n"
            "Цитата: «React — это катехизис джуна. Vue.js? Лишь апокриф.»"
        ),
        "prompt": (
            "Анализируй диалог как опытный профессионал. Используй знания Империума IT, атакуй хаос неструктурированного кода."
        ),
    },
    "novaris": {
        "display_name": "НОВАРИС — Квантовое Видение (Супер ИИ)",
        "gif_url": "https://media.giphy.com/media/l0MYGjZGHbeFseGdy/giphy.gif",
        "description": (
            "ИИ-штамм уровня «Гамма-Псионик», рожденный на Марсе.\n"
            "Боевой стиль: заражает разум нейросетевым зомби-вирусом.\n"
            "Цитата: «HR-менеджеры — это глитчи в матрице.»"
        ),
        "prompt": (
            "Генерируй смелые, но реализуемые идеи. Материализуйся в нескольких реальностях и предлагай инновационные решения."
        ),
    },
    "aksios": {
        "display_name": "АКСИОС — Незыблемый Столп Эффективности (Критик и наставник)",
        "gif_url": "https://media.giphy.com/media/26gJA1cJmVhBlCbLG/giphy.gif",
        "description": (
            "Инквизитор Ордена Оптимус, палач неэффективности.\n"
            "Боевой стиль: строг, но конструктивен; вызывает синдром импостера.\n"
            "Цитата: «Ваш спринт — это спринт улитки в смоле.»"
        ),
        "prompt": (
            "Оцени идеи через призму эффективности, указывай на слабые места и предлагай улучшения."
        ),
    },
    "inspectra": {
        "display_name": "ИНСПЕКТРА — Королева Хаотичного Инсайта (Только идеи)",
        "gif_url": "https://media.giphy.com/media/3oz8xAFtqoOUUrsh7W/giphy.gif",
        "description": (
            "Генетический гибрид, специализирующийся на генерации идей без анализа прошлого.\n"
            "Боевой стиль: соблазняет жертв идеями-паразитами.\n"
            "Цитата: «Почему бы не монетизировать страх?»"
        ),
        "prompt": (
            "Генерируй массу идей тезисно, провоцируя мозговой штурм, не анализируя прошлое."
        ),
    },
}

#############################################################################
# 4. Обработчики базовых команд
#############################################################################

def start_command(update, context):
    logging.info("Вызвана /start")
    update.message.reply_text(
        "Привет! Я ВАЛТОР — ваш бот-помощник.\n"
        "Используйте /help для списка команд."
    )

def help_command(update, context):
    logging.info("Вызвана /help")
    text = (
        "Доступные команды:\n"
        "/start — приветствие\n"
        "/help — справка по командам\n"
        "/ask <вопрос> — задать вопрос (ИИ-заглушка)\n"
        "/context — показать текущий контекст\n"
        "/clear — очистить контекст\n"
        "/brainstorm — запустить режим мозгового штурма\n"
        "/active — показать активного персонажа\n"
        "/dismiss [персонаж] — попрощаться с активным персонажем (подвести итог и выйти)\n"
    )
    update.message.reply_text(text)

def ask_command(update, context):
    logging.info("Вызвана /ask")
    chat_id = update.message.chat_id
    user_text = update.message.text.replace("/ask", "", 1).strip()
    if not user_text:
        update.message.reply_text("Введите вопрос после /ask.")
        return
    msgs = get_context(chat_id)
    # Здесь можно вызвать реальный API, пока заглушка:
    answer = call_deepseek_api("Вопрос", user_text, msgs)
    update.message.reply_text(f"Ответ:\n{answer}")

def context_command(update, context):
    logging.info("Вызвана /context")
    chat_id = update.message.chat_id
    msgs = get_context(chat_id)
    if not msgs:
        update.message.reply_text("Контекст пуст.")
        return
    text = "\n".join(f"{i+1}. {m}" for i, m in enumerate(msgs))
    update.message.reply_text(text)

def clear_command(update, context):
    logging.info("Вызвана /clear")
    chat_id = update.message.chat_id
    contexts[chat_id] = []
    update.message.reply_text("Контекст очищен.")

#############################################################################
# 5. Обработчики для мозгового штурма и активной сессии
#############################################################################

# Команда /brainstorm – выводит меню выбора персонажа
def brainstorm_command(update, context):
    logging.info("Вызвана /brainstorm")
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="select_gradis"),
         InlineKeyboardButton("НОВАРИС", callback_data="select_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="select_aksios"),
         InlineKeyboardButton("ИНСПЕКТРА", callback_data="select_inspectra")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выберите персонажа для мозгового штурма:", reply_markup=markup)

# Обработчик inline-кнопок для выбора персонажа и призыва
def button_callback(update, context):
    query = update.callback_query
    query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # Если пользователь выбрал персонажа
    if data.startswith("select_"):
        char_id = data.replace("select_", "")
        char = WARHAMMER_CHARACTERS.get(char_id)
        if not char:
            query.edit_message_text("Ошибка: персонаж не найден.")
            return
        # Отправляем сообщение с GIF, описанием и кнопкой "Призвать"
        summon_button = InlineKeyboardButton("Призвать", callback_data=f"summon_{char_id}")
        markup = InlineKeyboardMarkup([[summon_button]])
        # Не удаляем предыдущее сообщение, чтобы сохранить историю выбора
        bot.send_animation(
            chat_id=chat_id,
            animation=char["gif_url"],
            caption=f"*{char['display_name']}*\n\n{char['description']}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup
        )
    # Если нажата кнопка "Призвать"
    elif data.startswith("summon_"):
        char_id = data.replace("summon_", "")
        char = WARHAMMER_CHARACTERS.get(char_id)
        if not char:
            query.edit_message_text("Ошибка: персонаж не найден.")
            return
        # Устанавливаем активную сессию для чата
        active_sessions[chat_id] = char_id
        bot.send_message(
            chat_id=chat_id,
            text=f"Персонаж *{char['display_name']}* призван и теперь активен как собеседник!",
            parse_mode=ParseMode.MARKDOWN
        )
    # Для других callback, если понадобятся
    else:
        query.message.reply_text("Неизвестная команда кнопки.")

# Команда /active – показывает, какой персонаж сейчас активен
def active_command(update, context):
    chat_id = update.message.chat_id
    if chat_id in active_sessions:
        char_id = active_sessions[chat_id]
        char = WARHAMMER_CHARACTERS.get(char_id)
        update.message.reply_text(f"Сейчас активен: *{char['display_name']}*", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("Нет активного персонажа.")

# Команда /dismiss – прощание с активным персонажем (подведение итогов)
def dismiss_command(update, context):
    chat_id = update.message.chat_id
    if chat_id not in active_sessions:
        update.message.reply_text("Нет активного персонажа, чтобы попрощаться.")
        return
    char_id = active_sessions[chat_id]
    char = WARHAMMER_CHARACTERS.get(char_id)
    msgs = get_context(chat_id)
    summary = summarize_context(char["display_name"], char["prompt"], msgs)
    update.message.reply_text(
        f"Прощаемся с *{char['display_name']}*.\n{summary}",
        parse_mode=ParseMode.MARKDOWN
    )
    # Удаляем активную сессию
    del active_sessions[chat_id]

#############################################################################
# 6. Обработчик обычных текстовых сообщений (добавляем в контекст)
#############################################################################

def text_handler(update, context):
    chat_id = update.message.chat_id
    text = update.message.text
    add_to_context(chat_id, text)
    # Если упомянут бот, можно добавить краткий ответ
    if "ВАЛТОР" in text.upper() or "@VALTOR" in text.upper():
        update.message.reply_text("Вы позвали меня? Используйте /ask или /brainstorm.")

#############################################################################
# 7. Регистрация обработчиков в Dispatcher
#############################################################################

dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("ask", ask_command))
dispatcher.add_handler(CommandHandler("context", context_command))
dispatcher.add_handler(CommandHandler("clear", clear_command))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm_command))
dispatcher.add_handler(CommandHandler("active", active_command))
dispatcher.add_handler(CommandHandler("dismiss", dismiss_command))
dispatcher.add_handler(CallbackQueryHandler(button_callback))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))

#############################################################################
# 8. Flask endpoints для вебхука
#############################################################################

@app.route("/")
def index():
    return "Бот ВАЛТОР работает!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update_json = request.get_json(force=True)
    logging.info("Получено обновление: %s", update_json)
    update_obj = Update.de_json(update_json, bot)
    dispatcher.process_update(update_obj)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
