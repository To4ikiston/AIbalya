import os
import logging
import requests
from flask import Flask, request, jsonify
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ParseMode
)
from telegram.ext import (
    Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler, Filters
)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Чтение переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN", "NO_TOKEN_PROVIDED")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
APP_URL = os.getenv("APP_URL", "")          # Например, https://aibalya-1.onrender.com
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "")  # Секретный токен для вебхука

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=2, use_context=True)

#############################################
# Подключение к Supabase
#############################################
from supabase import create_client, Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_message_to_db(chat_id: int, thread_id: int, user_id: int, text: str):
    """Сохраняет сообщение в таблицу messages.
       Таблица должна быть создана в Supabase с полями:
       id, chat_id, thread_id, user_id, text, timestamp (default now())
    """
    try:
        data = {
            "chat_id": chat_id,
            "thread_id": thread_id,  # если тема отсутствует, можно передавать NULL (например, 0)
            "user_id": user_id,
            "text": text
        }
        supabase.table("messages").insert(data).execute()
    except Exception as e:
        logger.warning(f"Ошибка записи в DB: {e}")

def get_last_messages_db(chat_id: int, thread_id: int, limit=30):
    """Извлекает последние limit сообщений для данного chat_id и thread_id."""
    try:
        res = supabase.table("messages") \
            .select("text") \
            .eq("chat_id", chat_id) \
            .eq("thread_id", thread_id) \
            .order("timestamp", desc=True) \
            .limit(limit) \
            .execute()
        rows = res.data
        if rows:
            rows.reverse()
            return [r["text"] for r in rows]
        else:
            return []
    except Exception as e:
        logger.warning(f"Ошибка получения сообщений: {e}")
        return []

#############################################
# Функции для работы с состоянием персонажей
#############################################
# Для базовой реализации состояние персонажа будем хранить в памяти,
# а также обновлять в Supabase в таблице characters_state (если создана).
def update_character_state(chat_id: int, character_id: str):
    """
    Обновляет (увеличивает) счетчик призывов персонажа для данного чата.
    Таблица characters_state должна содержать: id, chat_id, character_id, summon_count, last_summon, story (jsonb), last_index.
    """
    try:
        res = supabase.table("characters_state") \
            .select("*") \
            .eq("chat_id", chat_id) \
            .eq("character_id", character_id) \
            .execute()
        rows = res.data
        if not rows:
            data = {
                "chat_id": chat_id,
                "character_id": character_id,
                "summon_count": 1,
                "last_index": 0
            }
            supabase.table("characters_state").insert(data).execute()
            return 1
        else:
            row = rows[0]
            new_count = row["summon_count"] + 1
            supabase.table("characters_state") \
                .update({"summon_count": new_count}) \
                .eq("id", row["id"]).execute()
            return new_count
    except Exception as e:
        logger.warning(f"Ошибка обновления состояния персонажа: {e}")
        return 1

#############################################
# Функции для вызова DeepSeek API
#############################################
def call_deepseek_api(prompt: str, context_msgs: list) -> str:
    """
    Вызывает DeepSeek API для генерации ответа.
    Если ключ не задан, возвращает заглушку.
    """
    if not DEEPSEEK_API_KEY:
        return f"DeepSeek API не настроен. Prompt: {prompt}\nКонтекст: {context_msgs}"
    url = "https://api.deepseek.ai/v1/ask"  # Уточните реальный URL API
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "question": prompt,
        "context": context_msgs  # передаем последние 30 сообщений (это можно ограничить)
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result.get("answer", "Нет ответа :(")
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return f"Ошибка DeepSeek: {e}"

def summarize_context(character_name: str, prompt: str, context_msgs: list) -> str:
    """
    Вызывает DeepSeek API для суммаризации (подведения итогов) перед dismiss.
    """
    if not DEEPSEEK_API_KEY:
        return f"Суммаризация: {character_name} говорит: {prompt}\nКонтекст: {context_msgs}"
    url = "https://api.deepseek.ai/v1/summarize"  # Уточните URL для суммаризации
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "prompt": prompt,
        "context": context_msgs
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result.get("summary", "Нет итогового ответа :(")
    except Exception as e:
        logger.error(f"DeepSeek Summarize error: {e}")
        return f"Ошибка суммаризации: {e}"

#############################################
# Двухшаговый режим для /ask
#############################################
awaiting_question = {}  # awaiting_question[chat_id] = True/False

def ask_command(update, context):
    chat_id = update.effective_chat.id
    awaiting_question[chat_id] = True
    update.message.reply_text("Введите свой вопрос отдельным сообщением:")

#############################################
# Данные о персонажах (Warhammer-стиль)
#############################################
# Используем новые ссылки (MP4) для гифок. Учтите, что Telegram send_animation работает с mp4.
WARHAMMER_CHARACTERS = {
    "gradis": {
        "display_name": "ГРАДИС — Архивариус Знания (Эксперт-человек)",
        "gif_url": "https://i.imgur.com/SgyqpOp.mp4",
        "description": (
            "Хранитель догматов Омниссиаха, превращающий опыт в алгоритмы. "
            "Боевой стиль: атакует хаос логическими вирусами. "
            "Цитата: «React — это катехизис джуна. Vue.js? Лишь апокриф.»"
        ),
        "prompt": "Анализируй диалог как опытный профессионал, подавляя хаос неструктурированного кода."
    },
    "novaris": {
        "display_name": "НОВАРИС — Квантовое Видение (Супер ИИ)",
        "gif_url": "https://i.imgur.com/6oEYvKs.mp4",
        "description": (
            "ИИ высшего уровня, рожденный на Марсе. "
            "Боевой стиль: заражает разум нейросетевым зомби-вирусом. "
            "Цитата: «HR-менеджеры — это глитчи в матрице.»"
        ),
        "prompt": "Генерируй смелые, но реализуемые идеи, материализуйся в нескольких реальностях."
    },
    "aksios": {
        "display_name": "АКСИОС — Незыблемый Столп Эффективности (Критик/наставник)",
        "gif_url": "https://i.imgur.com/q3vBdw3.mp4",
        "description": (
            "Инквизитор Ордена Оптимус, палач неэффективности. "
            "Боевой стиль: строг, но конструктивен. "
            "Цитата: «Ваш спринт — это спринт улитки в смоле.»"
        ),
        "prompt": "Оцени идеи через призму эффективности, указывай на слабые места и предлагай улучшения."
    },
    "inspectra": {
        "display_name": "ИНСПЕКТРА — Королева Хаотичного Инсайта (Только идеи)",
        "gif_url": "https://i.imgur.com/fSSPd5h.mp4",
        "description": (
            "Генетический гибрид, специализирующийся на генерации идей без анализа прошлого. "
            "Боевой стиль: соблазняет жертв идеями-паразитами. "
            "Цитата: «Почему бы не монетизировать страх?»"
        ),
        "prompt": "Генерируй массу идей тезисно, провоцируя мозговой штурм без излишней критики."
    },
}

#############################################
# Команды мозгового штурма
#############################################
active_characters = {}  # active_characters[chat_id] = character_id

def brainstorm_command(update, context):
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="select_gradis"),
         InlineKeyboardButton("НОВАРИС", callback_data="select_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="select_aksios"),
         InlineKeyboardButton("ИНСПЕКТРА", callback_data="select_inspectra")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выберите персонажа для мозгового штурма:", reply_markup=markup)

def button_callback(update, context):
    query = update.callback_query
    data = query.data
    query.answer()
    chat_id = query.message.chat_id
    # Если пользователь выбрал персонажа из меню
    if data.startswith("select_"):
        char_id = data.replace("select_", "")
        char = WARHAMMER_CHARACTERS.get(char_id)
        if not char:
            query.message.reply_text("Ошибка: персонаж не найден.")
            return
        # Отправляем сообщение с GIF, описанием и кнопкой "Призвать"
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
        # Обновляем состояние персонажа в Supabase
        summon_count = update_character_state(chat_id, char_id)
        # Устанавливаем активного персонажа для чата
        active_characters[chat_id] = char_id
        greeting = f"Призыв #{summon_count}: *{char['display_name']}* теперь активен и вступает в диалог!"
        bot.send_message(
            chat_id=chat_id,
            text=greeting,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        query.message.reply_text("Неизвестная команда кнопки.")

#############################################
# Команда /active – показать активного персонажа
#############################################
def active_command(update, context):
    chat_id = update.effective_chat.id
    if chat_id in active_characters:
        char_id = active_characters[chat_id]
        char = WARHAMMER_CHARACTERS.get(char_id)
        update.message.reply_text(f"Активный персонаж: *{char['display_name']}*", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("Нет активного персонажа.")

#############################################
# Команда /dismiss – завершить сессию персонажа
#############################################
def dismiss_command(update, context):
    chat_id = update.effective_chat.id
    if chat_id not in active_characters:
        update.message.reply_text("Нет активного персонажа для прощания.")
        return
    char_id = active_characters[chat_id]
    char = WARHAMMER_CHARACTERS.get(char_id)
    msgs = get_last_messages_db(chat_id, thread_id=update.effective_chat.id, limit=30)
    summary = summarize_context(char["display_name"], char["prompt"], msgs)
    update.message.reply_text(f"Прощаемся с *{char['display_name']}*.\n{summary}", parse_mode=ParseMode.MARKDOWN)
    # Здесь можно сохранить историю сессии в отдельную таблицу conversation_history
    # (реализация опциональна)
    del active_characters[chat_id]

#############################################
# Автоматический ответ активного персонажа
#############################################
def auto_dialog_handler(update, context):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if update.effective_user.is_bot or text.startswith("/"):
        return
    # Сохраняем сообщение в базу
    thread_id = update.message.message_thread_id or update.effective_chat.id
    save_message_to_db(chat_id, thread_id, user_id, text)
    # Если в чате есть активный персонаж, он отвечает автоматически
    if chat_id in active_characters:
        char_id = active_characters[chat_id]
        char = WARHAMMER_CHARACTERS.get(char_id)
        msgs = get_last_messages_db(chat_id, thread_id, limit=30)
        full_prompt = f"{char['prompt']}\nПользователь сказал: {text}\nОтветь как {char['display_name']}."
        answer = call_deepseek_api(prompt=full_prompt, context_msgs=msgs)
        bot.send_message(chat_id=chat_id, text=answer)

#############################################
# Регистрация обработчиков
#############################################
dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("ask", ask_command))
dispatcher.add_handler(CommandHandler("context", context_command))
dispatcher.add_handler(CommandHandler("clear", clear_command))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm_command))
dispatcher.add_handler(CommandHandler("active", active_command))
dispatcher.add_handler(CommandHandler("dismiss", dismiss_command))
dispatcher.add_handler(CallbackQueryHandler(button_callback))
dispatcher.add_handler(MessageHandler(Filters.text, auto_dialog_handler))

#############################################
# Автоматическая установка вебхука при запуске
#############################################
def set_webhook():
    if APP_URL:
        webhook_url = f"{APP_URL}/{BOT_TOKEN}"
        # Можно добавить секретный токен в параметр secret_token, если хотите
        bot.set_webhook(url=webhook_url, secret_token=SECRET_TOKEN)
        logger.info(f"Webhook установлен: {webhook_url}")
    else:
        logger.warning("APP_URL не задан. Установите вебхук вручную.")

#############################################
# Flask endpoints
#############################################
@app.route("/")
def index():
    return "Бот ВАЛТОР работает с вебхуками!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook_endpoint():
    update_json = request.get_json(force=True)
    logger.info(f"Получено обновление: {update_json}")
    update_obj = Update.de_json(update_json, bot)
    dispatcher.process_update(update_obj)
    return jsonify({"ok": True})

#############################################
# Основной запуск
#############################################
if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
