import os
import logging
from flask import Flask, request, jsonify
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ParseMode
)
from telegram.ext import (
    Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler, Filters
)

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "NO_TOKEN_PROVIDED")
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=2, use_context=True)

#############################################################################
# 1. Хранение контекста + активного персонажа
#############################################################################

# contexts[chat_id] = список (строк) сообщений пользователей
contexts = {}

def get_context(chat_id: int):
    if chat_id not in contexts:
        contexts[chat_id] = []
    return contexts[chat_id]

def add_user_message(chat_id: int, text: str):
    """Добавляет текст пользователя в контекст (но не команду и не бота)."""
    ctx = get_context(chat_id)
    ctx.append(text)
    # Ограничим до 100 сообщений
    if len(ctx) > 100:
        contexts[chat_id] = ctx[-100:]

# active_sessions[chat_id] = "gradis"/"novaris"/"aksios"/"inspectra" или None
active_sessions = {}

#############################################################################
# 2. Заглушки для DeepSeek (в будущем замените на реальный HTTP-запрос)
#############################################################################

def call_deepseek_api(character_name: str, prompt: str, context_messages: list) -> str:
    """
    Генерирует ответ от лица выбранного персонажа (пока что — заглушка).
    """
    last30 = "\n".join(context_messages[-30:]) if context_messages else "Нет сообщений."
    return (
        f"=== Ответ от {character_name} ===\n"
        f"Промт: {prompt}\n\n"
        f"Контекст (последние 30 сообщений):\n{last30}\n\n"
        f"(Это заглушка для DeepSeek.)"
    )

def summarize_context(character_name: str, prompt: str, context_messages: list) -> str:
    """
    При /dismiss персонаж подводит итог (заглушка).
    """
    last30 = "\n".join(context_messages[-30:]) if context_messages else "Нет сообщений."
    return (
        f"=== Итог от {character_name} ===\n"
        f"Промт: {prompt}\n\n"
        f"Итоговая сводка (последние 30 сообщений):\n{last30}\n\n"
        f"(Заглушка для финальной суммаризации)"
    )

#############################################################################
# 3. Данные о персонажах (Warhammer-стиль)
#############################################################################

WARHAMMER_CHARACTERS = {
    "gradis": {
        "display_name": "ГРАДИС — Архивариус Знания (Эксперт-человек)",
        "gif_url": "https://media.giphy.com/media/3o7abB06u9bNzA8lu8/giphy.gif",
        "description": (
            "Хранитель догматов Омниссиаха. Боевой стиль: логические вирусы.\n"
            "Цитата: «React — это катехизис джуна. Vue.js? Лишь апокриф.»"
        ),
        "prompt": (
            "Анализируй диалог как опытный профессионал, подавляя хаос кода."
        ),
    },
    "novaris": {
        "display_name": "НОВАРИС — Квантовое Видение (Супер ИИ)",
        "gif_url": "https://media.giphy.com/media/l0MYGjZGHbeFseGdy/giphy.gif",
        "description": (
            "ИИ уровня «Гамма-Псионик». Боевой стиль: нейросетевой зомби-вирус.\n"
            "Цитата: «HR-менеджеры — это глитчи в матрице.»"
        ),
        "prompt": (
            "Генерируй смелые идеи, с инновационным уклоном."
        ),
    },
    "aksios": {
        "display_name": "АКСИОС — Незыблемый Столп Эффективности (Критик/наставник)",
        "gif_url": "https://media.giphy.com/media/26gJA1cJmVhBlCbLG/giphy.gif",
        "description": (
            "Инквизитор Ордена Оптимус. Строг, но конструктивен.\n"
            "Цитата: «Ваш спринт — это спринт улитки в смоле.»"
        ),
        "prompt": (
            "Оцени идеи через призму эффективности, указывай на слабые места."
        ),
    },
    "inspectra": {
        "display_name": "ИНСПЕКТРА — Королева Хаотичного Инсайта (Только идеи)",
        "gif_url": "https://media.giphy.com/media/3oz8xAFtqoOUUrsh7W/giphy.gif",
        "description": (
            "Генерация идей без анализа прошлого. Демонесса Слаанеш.\n"
            "Цитата: «Почему бы не монетизировать страх?»"
        ),
        "prompt": (
            "Генерируй массу идей, провоцируя мозговой штурм, без критики."
        ),
    },
}

#############################################################################
# 4. Команды: /start, /help, /ask, /context, /clear, /brainstorm, /active, /dismiss
#############################################################################

from telegram import ReplyKeyboardMarkup

def start_command(update, context):
    keyboard = [
        ["/brainstorm", "/ask"],
        ["/context", "/clear"],
        ["/help", "/dismiss"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text(
        "Привет! Я ВАЛТОР. Используйте кнопки для быстрого доступа к командам.",
        reply_markup=reply_markup
    )

def help_command(update, context):
    text = (
        "Доступные команды:\n"
        "/start — запуск с клавиатурой\n"
        "/help — справка\n"
        "/ask <вопрос> — задать вопрос (заглушка)\n"
        "/context — показать контекст\n"
        "/clear — очистить контекст\n"
        "/brainstorm — выбор персонажа Warhammer\n"
        "/active — показать активного персонажа\n"
        "/dismiss — завершить сессию, подвести итог"
    )
    update.message.reply_text(text)

def ask_command(update, context):
    chat_id = update.message.chat_id
    user_text = update.message.text.replace("/ask", "", 1).strip()
    if not user_text:
        update.message.reply_text("Введите вопрос после /ask.")
        return
    # Берём контекст и вызываем заглушку
    msgs = get_context(chat_id)
    answer = call_deepseek_api("Вопрос", user_text, msgs)
    update.message.reply_text(answer)

def context_command(update, context):
    chat_id = update.message.chat_id
    msgs = get_context(chat_id)
    if not msgs:
        update.message.reply_text("Контекст пуст.")
        return
    text = "\n".join(f"{i+1}. {m}" for i, m in enumerate(msgs))
    update.message.reply_text(text)

def clear_command(update, context):
    chat_id = update.message.chat_id
    contexts[chat_id] = []
    update.message.reply_text("Контекст очищен.")

def brainstorm_command(update, context):
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="select_gradis"),
         InlineKeyboardButton("НОВАРИС", callback_data="select_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="select_aksios"),
         InlineKeyboardButton("ИНСПЕКТРА", callback_data="select_inspectra")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выберите персонажа для мозгового штурма:", reply_markup=markup)

def active_command(update, context):
    chat_id = update.message.chat_id
    if chat_id in active_sessions:
        char_id = active_sessions[chat_id]
        char = WARHAMMER_CHARACTERS.get(char_id)
        update.message.reply_text(
            f"Сейчас активен: *{char['display_name']}*",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        update.message.reply_text("Нет активного персонажа.")

def dismiss_command(update, context):
    """Выключаем активного персонажа (подведение итогов)."""
    chat_id = update.message.chat_id
    if chat_id not in active_sessions:
        update.message.reply_text("Нет активного персонажа.")
        return
    char_id = active_sessions[chat_id]
    char = WARHAMMER_CHARACTERS[char_id]
    msgs = get_context(chat_id)
    summary = summarize_context(char["display_name"], char["prompt"], msgs)
    update.message.reply_text(summary)
    del active_sessions[chat_id]
    update.message.reply_text(f"Персонаж {char['display_name']} ушёл из чата.")

#############################################################################
# 5. Inline-кнопки /brainstorm (выбор персонажа + призыв)
#############################################################################

def button_callback(update, context):
    query = update.callback_query
    data = query.data
    query.answer()
    chat_id = query.message.chat_id

    if data.startswith("select_"):
        char_id = data.replace("select_", "")
        char = WARHAMMER_CHARACTERS.get(char_id)
        if not char:
            query.message.reply_text("Ошибка: персонаж не найден.")
            return
        # Кнопка "Призвать"
        summon_btn = InlineKeyboardButton("Призвать", callback_data=f"summon_{char_id}")
        markup = InlineKeyboardMarkup([[summon_btn]])
        bot.send_animation(
            chat_id=chat_id,
            animation=char["gif_url"],
            caption=f"*{char['display_name']}*\n\n{char['description']}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup
        )

    elif data.startswith("summon_"):
        char_id = data.replace("summon_", "")
        char = WARHAMMER_CHARACTERS.get(char_id)
        if not char:
            query.message.reply_text("Ошибка: персонаж не найден.")
            return
        active_sessions[chat_id] = char_id
        bot.send_message(
            chat_id=chat_id,
            text=f"Персонаж *{char['display_name']}* теперь активен и участвует в диалоге!",
            parse_mode=ParseMode.MARKDOWN
        )

    else:
        query.message.reply_text("Неизвестная команда кнопки.")

#############################################################################
# 6. Автоматическое участие персонажа
#############################################################################

def auto_dialog_handler(update, context):
    """
    Если есть активный персонаж, он отвечает автоматически 
    на каждое новое сообщение пользователя (не команду и не бота).
    """
    message = update.message
    if not message or not message.text:
        return  # Защита от пустых/медиа-сообщений

    chat_id = message.chat_id
    user_id = message.from_user.id

    # Проверяем, не бот ли это отправил (чтобы не зациклиться)
    if message.from_user.is_bot:
        return

    text = message.text.strip()
    # Если это команда (начинается с /), не обрабатываем здесь
    if text.startswith("/"):
        return

    # Добавим текст в контекст
    add_to_context(chat_id, text)

    # Если есть активный персонаж, он формирует ответ
    if chat_id in active_sessions:
        char_id = active_sessions[chat_id]
        char = WARHAMMER_CHARACTERS.get(char_id)
        # Вызываем заглушку DeepSeek
        ctx = get_context(chat_id)
        answer = call_deepseek_api(char["display_name"], char["prompt"], ctx)
        # Отправляем ответ
        bot.send_message(
            chat_id=chat_id,
            text=answer
        )

#############################################################################
# 7. Регистрация обработчиков
#############################################################################

from telegram.ext import (
    Filters
)

# Команды
dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("ask", ask_command))
dispatcher.add_handler(CommandHandler("context", context_command))
dispatcher.add_handler(CommandHandler("clear", clear_command))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm_command))
dispatcher.add_handler(CommandHandler("active", active_command))
dispatcher.add_handler(CommandHandler("dismiss", dismiss_command))

# Inline-кнопки (brainstorm)
dispatcher.add_handler(CallbackQueryHandler(button_callback))

# Авто-диалог — высокий приоритет, чтобы срабатывал после команд
dispatcher.add_handler(MessageHandler(Filters.text, auto_dialog_handler), group=1)

#############################################################################
# 8. Flask endpoints (вебхук)
#############################################################################

@app.route("/")
def index():
    return "Бот ВАЛТОР работает (авто-участие персонажа)!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update_json = request.get_json(force=True)
    logging.info("Получено обновление: %s", update_json)
    update_obj = Update.de_json(update_json, bot)
    dispatcher.process_update(update_obj)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
