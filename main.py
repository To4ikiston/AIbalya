import os
import logging
import openai
from flask import Flask, request, jsonify
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler, Filters

# ==================== Настройка логирования ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== Инициализация Flask приложения ====================
app = Flask(__name__)

# ==================== Получение переменных окружения ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "NO_TOKEN_PROVIDED")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
APP_URL = os.getenv("APP_URL", "")         # Например, https://aibalya-1.onrender.com
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "") # Секретный токен для вебхука

# ==================== Инициализация бота и диспетчера ====================
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=2, use_context=True)

# ==================== Настройка DeepSeek через openai ====================
openai.api_key = DEEPSEEK_API_KEY
openai.api_base = "https://api.deepseek.com"  # новый API-URL

# ==================== Подключение к Supabase ====================
from supabase import create_client, Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_message_to_db(chat_id: int, thread_id: int, user_id: int, text: str):
    """Сохраняет сообщение в таблицу messages."""
    try:
        data = {
            "chat_id": chat_id,
            "thread_id": thread_id,  # если тема не используется, можно передавать chat_id
            "user_id": user_id,
            "text": text
        }
        supabase.table("messages").insert(data).execute()
    except Exception as e:
        logger.warning(f"Ошибка записи в DB: {e}")

def get_last_messages_db(chat_id: int, thread_id: int, limit=30):
    """Извлекает последние 'limit' сообщений для данного chat_id и thread_id."""
    try:
        res = supabase.table("messages") \
            .select("text") \
            .eq("chat_id", chat_id) \
            .eq("thread_id", thread_id) \
            .order("timestamp", desc=True) \
            .limit(limit) \
            .execute()
        rows = res.data or []
        rows.reverse()
        return [r["text"] for r in rows]
    except Exception as e:
        logger.warning(f"Ошибка получения сообщений: {e}")
        return []

def save_conversation_history(chat_id: int, thread_id: int, active_character: str, conversation: list):
    """Сохраняет историю сессии в таблицу conversation_history."""
    conversation_text = "\n".join(conversation)
    data = {
        "chat_id": chat_id,
        "thread_id": thread_id,
        "conversation": conversation_text,
        "active_character": active_character,
        "session_end": "now()"
    }
    try:
        supabase.table("conversation_history").insert(data).execute()
        logger.info("История сессии сохранена успешно.")
    except Exception as e:
        logger.warning(f"Ошибка сохранения истории сессии: {e}")

def update_character_state(chat_id: int, character_id: str):
    """
    Обновляет (увеличивает) счетчик призывов персонажа для данного чата.
    Если записи нет, создаёт новую.
    """
    try:
        res = supabase.table("characters_state") \
            .select("*") \
            .eq("chat_id", chat_id) \
            .eq("character_id", character_id) \
            .execute()
        rows = res.data or []
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

def call_deepseek_api(prompt: str, context_msgs: list) -> str:
    """
    Вызывает DeepSeek API для генерации ответа через openai.ChatCompletion.create.
    Использует модель "deepseek-chat".
    """
    messages = [
        {"role": "system", "content": "You are a helpful assistant."}
    ]
    if context_msgs:
        context_text = "\n".join(context_msgs)
        messages.append({"role": "system", "content": f"Context:\n{context_text}"})
    messages.append({"role": "user", "content": prompt})
    try:
        response = openai.ChatCompletion.create(
            model="deepseek-chat",
            messages=messages,
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return f"Ошибка DeepSeek: {e}"

def summarize_context(character_name: str, prompt: str, context_msgs: list) -> str:
    """
    Вызывает DeepSeek API для суммаризации через openai.ChatCompletion.create.
    """
    messages = [
        {"role": "system", "content": "You are a helpful assistant that summarizes conversations."}
    ]
    if context_msgs:
        context_text = "\n".join(context_msgs)
        messages.append({"role": "system", "content": f"Conversation Context:\n{context_text}"})
    messages.append({"role": "user", "content": prompt})
    try:
        response = openai.ChatCompletion.create(
            model="deepseek-chat",
            messages=messages,
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek Summarize error: {e}")
        return f"Ошибка суммаризации: {e}"

# ==================== Двухшаговый режим для /ask ====================
awaiting_question = {}  # awaiting_question[chat_id] = True/False

def ask_command(update, context):
    """
    При вызове /ask устанавливает флаг ожидания вопроса.
    Следующее текстовое сообщение будет обработано как вопрос.
    """
    chat_id = update.effective_chat.id
    awaiting_question[chat_id] = True
    update.message.reply_text("Введите свой вопрос отдельным сообщением:")

# ==================== Команда /start ====================
def start_command(update, context):
    """Отправляет простое текстовое приветствие."""
    update.message.reply_text("Привет! Я ВАЛТОР — ваш бот-помощник. Используйте /help для списка команд.")

# ==================== Команда /help ====================
def help_command(update, context):
    """Выводит список доступных команд с описанием."""
    help_text = (
        "/start — Приветствие\n"
        "/help — Справка по командам\n"
        "/ask <вопрос> — Задать вопрос (двухшаговый режим)\n"
        "/context — Показать последние 30 сообщений\n"
        "/clear — Очистить контекст\n"
        "/brainstorm — Начать мозговой штурм (выбор персонажа)\n"
        "/active — Показать активных персонажей\n"
        "/dismiss — Завершить сессию персонажей и подвести итог\n"
        "/summarize — Подвести итог переписки (опционально)\n"
        "/stats — Статистика по теме (опционально)"
    )
    update.message.reply_text(help_text)

# ==================== Данные о персонажах (Warhammer-стиль) ====================
# Используем прямые ссылки на MP4 файлы
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

# ==================== Команды мозгового штурма ====================
# Поддержка нескольких активных персонажей: для каждого чата хранится список.
active_characters = {}  # active_characters[chat_id] = список character_id

def brainstorm_command(update, context):
    """Выводит меню выбора персонажа для мозгового штурма (inline кнопки)."""
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="select_gradis"),
         InlineKeyboardButton("НОВАРИС", callback_data="select_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="select_aksios"),
         InlineKeyboardButton("ИНСПЕКТРА", callback_data="select_inspectra")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выберите персонажа для мозгового штурма:", reply_markup=markup)

def button_callback(update, context):
    """Обрабатывает выбор персонажа и кнопку 'Призвать'."""
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
        # Отправляем видео с описанием и inline кнопкой "Призвать"
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
        # Добавляем персонажа в список активных для данного чата
        active_characters.setdefault(chat_id, [])
        if char_id not in active_characters[chat_id]:
            active_characters[chat_id].append(char_id)
        greeting = f"Призыв #{summon_count}: *{char['display_name']}* теперь активен и участвует в диалоге!"
        bot.send_message(
            chat_id=chat_id,
            text=greeting,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        query.message.reply_text("Неизвестная команда кнопки.")

# ==================== Команда /active ====================
def active_command(update, context):
    """Показывает список активных персонажей."""
    chat_id = update.effective_chat.id
    if chat_id in active_characters and active_characters[chat_id]:
        names = []
        for char_id in active_characters[chat_id]:
            char = WARHAMMER_CHARACTERS.get(char_id)
            if char:
                names.append(char["display_name"])
        update.message.reply_text("Активные персонажи:\n" + "\n".join(names), parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("Нет активного персонажа.")

# ==================== Команда /dismiss ====================
def dismiss_command(update, context):
    """
    Завершает сессию всех активных персонажей: подводит итоги, сохраняет историю сессии и сбрасывает список активных персонажей.
    """
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or update.effective_chat.id
    if chat_id not in active_characters or not active_characters[chat_id]:
        update.message.reply_text("Нет активных персонажей для прощания.")
        return
    for char_id in active_characters[chat_id]:
        char = WARHAMMER_CHARACTERS.get(char_id)
        msgs = get_last_messages_db(chat_id, thread_id, limit=30)
        summary = summarize_context(char["display_name"], char["prompt"], msgs)
        update.message.reply_text(f"Прощаемся с *{char['display_name']}*.\n{summary}", parse_mode=ParseMode.MARKDOWN)
        conv = get_last_messages_db(chat_id, thread_id, limit=100)
        try:
            data = {
                "chat_id": chat_id,
                "thread_id": thread_id,
                "conversation": "\n".join(conv),
                "active_character": char["display_name"]
            }
            supabase.table("conversation_history").insert(data).execute()
            logger.info("История сессии сохранена.")
        except Exception as e:
            logger.warning(f"Ошибка сохранения истории сессии: {e}")
    active_characters[chat_id] = []

# ==================== Команда /help ====================
def help_command(update, context):
    """Выводит список доступных команд с кратким описанием."""
    help_text = (
        "/start — Приветствие\n"
        "/help — Справка по командам\n"
        "/ask <текст вопроса> — Задать вопрос (двухшаговый режим)\n"
        "/context — Показать последние 30 сообщений\n"
        "/clear — Очистить контекст\n"
        "/brainstorm — Начать мозговой штурм (выбор персонажа)\n"
        "/active — Показать активных персонажей\n"
        "/dismiss — Завершить сессию персонажей и подвести итог\n"
        "/summarize — Подвести итог переписки (опционально)\n"
        "/stats — Показать статистику (опционально)"
    )
    update.message.reply_text(help_text)

# ==================== Обработчик текстовых сообщений ====================
def text_message_handler(update, context):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if update.effective_user.is_bot or text.startswith("/"):
        return
    thread_id = update.message.message_thread_id or update.effective_chat.id
    save_message_to_db(chat_id, thread_id, user_id, text)
    if awaiting_question.get(chat_id, False):
        awaiting_question[chat_id] = False
        msgs = get_last_messages_db(chat_id, thread_id, limit=30)
        answer = call_deepseek_api(prompt=text, context_msgs=msgs)
        update.message.reply_text(f"Ответ:\n{answer}")
        return
    if chat_id in active_characters and active_characters[chat_id]:
        for char_id in active_characters[chat_id]:
            char = WARHAMMER_CHARACTERS.get(char_id)
            msgs = get_last_messages_db(chat_id, thread_id, limit=30)
            full_prompt = f"{char['prompt']}\nПользователь сказал: {text}\nОтветь как {char['display_name']}."
            answer = call_deepseek_api(prompt=full_prompt, context_msgs=msgs)
            bot.send_message(chat_id=chat_id, text=answer)

# ==================== Автоматическая установка вебхука ====================
def set_webhook():
    if APP_URL:
        webhook_url = f"{APP_URL}/{BOT_TOKEN}"
        bot.set_webhook(url=webhook_url, secret_token=SECRET_TOKEN)
        logger.info(f"Webhook установлен: {webhook_url}")
    else:
        logger.warning("APP_URL не задан. Установите вебхук вручную.")

# ==================== Регистрация обработчиков ====================
dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("ask", ask_command))
dispatcher.add_handler(CommandHandler("context", lambda update, context: update.message.reply_text(
    "\n".join(get_last_messages_db(update.effective_chat.id, update.message.message_thread_id or update.effective_chat.id, limit=30))
)))
dispatcher.add_handler(CommandHandler("clear", lambda update, context: (
    supabase.table("messages").delete().eq("chat_id", update.effective_chat.id).execute(),
    update.message.reply_text("Контекст очищен.")
)))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm_command))
dispatcher.add_handler(CommandHandler("active", active_command))
dispatcher.add_handler(CommandHandler("dismiss", dismiss_command))
dispatcher.add_handler(CallbackQueryHandler(button_callback))
dispatcher.add_handler(MessageHandler(Filters.text, text_message_handler))

# ==================== Flask эндпоинты ====================
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

# ==================== Основной запуск ====================
if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
