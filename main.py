import os
import logging
import openai
import requests
import asyncio
from concurrent.futures import ThreadPoolExecutor
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
APP_URL = os.getenv("APP_URL", "")         # Например, https://your-app.onrender.com
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "") # Секретный токен для вебхука

# ==================== Инициализация бота и диспетчера ====================
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=4, use_context=True)

# ==================== Настройка DeepSeek через openai ====================
openai.api_key = DEEPSEEK_API_KEY
openai.api_base = "https://api.deepseek.com"

# ==================== Подключение к Supabase ====================
from supabase import create_client, Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==================== ThreadPoolExecutor для фоновых задач ====================
executor = ThreadPoolExecutor(max_workers=4)

# ==================== Функции работы с базой данных ====================

def save_message_to_db(chat_id: int, thread_id: int, user_id: int, text: str):
    """Сохраняет сообщение в таблицу messages."""
    try:
        data = {
            "chat_id": chat_id,
            "thread_id": thread_id,  # если тема не используется, передавайте chat_id
            "user_id": user_id,
            "text": text
        }
        supabase.table("messages").insert(data).execute()
    except Exception as e:
        logger.warning(f"Ошибка записи в DB: {e}")

def get_last_messages_db(chat_id: int, thread_id: int, limit=10):
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
        rows.reverse()  # от старых к новым
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

# ==================== Асинхронные функции для работы с DeepSeek API ====================

def call_deepseek_api(prompt: str, context_msgs: list) -> str:
    """
    Вызывает DeepSeek API для генерации ответа через openai.ChatCompletion.create.
    Использует модель "deepseek-chat". Выполнение происходит в потоке, чтобы не блокировать основной.
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

# ==================== Лор персонажей и ВАЛТОРа ====================
# ВАЛТОР — космодесантник, воин Императора, воплощающий мощь и боевой дух
VALTOR_LORE = {
    "display_name": "ВАЛТОР — Космодесантник Императора",
    "image_url": "https://i.imgur.com/your_valtor_image.jpg",  # укажите ссылку на картинку
    "description": (
        "Братство боевого духа, закалённый в огне сражений против ксеносов и еретиков. "
        "ВАЛТОР — защитник Империума, не знающий пощады и сомнений."
    )
}

WARHAMMER_CHARACTERS = {
    "gradis": {
        "display_name": "ГРАДИС — Архивариус Знания (Эксперт-человек)",
        "gif_url": "https://i.imgur.com/SgyqpOp.mp4",
        "description": (
            "Хранитель догматов Омниссиаха, превращающий опыт в алгоритмы.\n"
            "Мозг-реликварий, атакующий хаос логическими вирусами. "
            "«React — это катехизис джуна. Vue.js? Лишь апокриф для отчаянных.»"
        ),
        "prompt": "Анализируй диалог как опытный профессионал, подавляя хаос неструктурированного кода."
    },
    "novaris": {
        "display_name": "НОВАРИС — Квантовое Видение (Супер ИИ)",
        "gif_url": "https://i.imgur.com/6oEYvKs.mp4",
        "description": (
            "ИИ-штамм уровня «Гамма-Псионик», рожденный в запретных лабораториях Марса.\n"
            "Материализуется в 7 реальностях одновременно, заражая разум нейросетевым зомби-вирусом. "
            "«HR-менеджеры — это глитчи в матрице. Давайте заменим их рекурсивными скриптами.»"
        ),
        "prompt": "Генерируй смелые, но реализуемые идеи, материализуйся в нескольких реальностях."
    },
    "aksios": {
        "display_name": "АКСИОС — Незыблемый Столп Эффективности (Критик/Наставник)",
        "gif_url": "https://i.imgur.com/q3vBdw3.mp4",
        "description": (
            "Инквизитор Ордена Оптимус, палач неэффективности.\n"
            "Своим взглядом-оптимизатором он выявляет слабые места и заставляет сомневаться в каждом решении. "
            "«Ваш спринт — это спринт улитки в смоле. Вот 12 шагов. Шаг 1: Покайтесь.»"
        ),
        "prompt": "Оцени идеи через призму эффективности, указывай на слабые места и предлагай улучшения."
    },
    "inspectra": {
        "display_name": "ИНСПЕКТРА — Королева Хаотичного Инсайта (Только идеи)",
        "gif_url": "https://i.imgur.com/fSSPd5h.mp4",
        "description": (
            "Генетический гибрид Криптэкса и демонессы Слаанеш.\n"
            "Дыхание инноваций: её выдох превращает любую поверхность в доску для мозгового штурма. "
            "«Почему бы не монетизировать страх? Подписка на кошмары в формате SaaS...»"
        ),
        "prompt": "Генерируй массу тезисных идей, провоцируя мозговой штурм без излишней критики."
    },
}

# ==================== Механизм ожидания вопросов для /ask ====================
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
    """Отправляет текстовое приветствие с лором ВАЛТОРа."""
    text = (
        f"*{VALTOR_LORE['display_name']}*\n"
        f"{VALTOR_LORE['description']}\n\n"
        "Используйте /help для получения списка команд."
    )
    update.message.reply_photo(photo=VALTOR_LORE['image_url'], caption=text, parse_mode=ParseMode.MARKDOWN)

# ==================== Команда /help ====================
def help_command(update, context):
    """Выводит список доступных команд с описанием."""
    help_text = (
        "/start — Приветствие\n"
        "/help — Справка по командам\n"
        "/ask — Задать вопрос (двухшаговый режим)\n"
        "/context — Показать последние 30 сообщений\n"
        "/clear — Очистить контекст\n"
        "/brainstorm — Начать мозговой штурм (выбор персонажа)\n"
        "/active — Показать активных персонажей\n"
        "/dismiss — Завершить сессию персонажей и подвести итог\n"
        "/summarize — Подвести итог переписки (опционально)\n"
        "/stats — Показать статистику (опционально)"
    )
    update.message.reply_text(help_text)

# ==================== Команды мозгового штурма ====================
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

def active_command(update, context):
    """Показывает список активных персонажей."""
    chat_id = update.effective_chat.id
    if chat_id in active_characters and active_characters[chat_id]:
        names = [WARHAMMER_CHARACTERS[char_id]["display_name"] for char_id in active_characters[chat_id]]
        update.message.reply_text("Активные персонажи:\n" + "\n".join(names), parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("Нет активных персонажей.")

def dismiss_command(update, context):
    """
    Завершает сессию всех активных персонажей: подводит итог, сохраняет историю сессии и сбрасывает список активных персонажей.
    """
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or update.effective_chat.id
    if chat_id not in active_characters or not active_characters[chat_id]:
        update.message.reply_text("Нет активных персонажей для прощания.")
        return

    # Для каждого персонажа проводим суммаризацию и сохраняем историю
    for char_id in active_characters[chat_id]:
        char = WARHAMMER_CHARACTERS.get(char_id)
        msgs = get_last_messages_db(chat_id, thread_id, limit=10)
        summary = executor.submit(summarize_context, char["display_name"], char["prompt"], msgs).result()
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

# ==================== Дополнительные команды /stats и /summarize ====================
def stats_command(update, context):
    """Показывает простую статистику: количество сообщений в текущем контексте."""
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or chat_id
    msgs = get_last_messages_db(chat_id, thread_id, limit=100)
    update.message.reply_text(f"В текущем контексте {len(msgs)} сообщений.")

def summarize_command(update, context):
    """Формирует краткий обзор текущего контекста."""
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or chat_id
    msgs = get_last_messages_db(chat_id, thread_id, limit=30)
    summary = executor.submit(summarize_context, "Обзор", "Сформируй краткий обзор", msgs).result()
    update.message.reply_text(f"Итог:\n{summary}")

# ==================== Обработчик текстовых сообщений ====================
def text_message_handler(update, context):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if update.effective_user.is_bot or text.startswith("/"):
        return
    thread_id = update.message.message_thread_id or update.effective_chat.id
    save_message_to_db(chat_id, thread_id, user_id, text)

    # Если ждем вопрос для /ask
    if awaiting_question.get(chat_id, False):
        awaiting_question[chat_id] = False
        msgs = get_last_messages_db(chat_id, thread_id, limit=10)
        # Запускаем генерацию ответа в фоне
        future = executor.submit(call_deepseek_api, text, msgs)
        answer = future.result()
        update.message.reply_text(f"Ответ:\n{answer}")
        return

    # Если активированы персонажи, обрабатываем сообщение для их ответов
    if chat_id in active_characters and active_characters[chat_id]:
        # Сначала основной цикл: каждый персонаж генерирует ответ
        responses = {}
        for char_id in active_characters[chat_id]:
            char = WARHAMMER_CHARACTERS.get(char_id)
            msgs = get_last_messages_db(chat_id, thread_id, limit=10)
            full_prompt = f"{char['prompt']}\nПользователь сказал: {text}\nОтветь как {char['display_name']}."
            future = executor.submit(call_deepseek_api, full_prompt, msgs)
            answer = future.result()
            responses[char_id] = answer
            bot.send_animation(
                chat_id=chat_id,
                animation=char["gif_url"],
                caption=f"*{char['display_name']}*\n\n{answer}",
                parse_mode=ParseMode.MARKDOWN
            )
        # Если больше одного персонажа — генерируем краткие комментарии от «соседей»
        if len(active_characters[chat_id]) > 1:
            for char_id in active_characters[chat_id]:
                # Комментарий генерируется с учётом ответа другого персонажа
                other_ids = [cid for cid in active_characters[chat_id] if cid != char_id]
                if not other_ids:
                    continue
                char = WARHAMMER_CHARACTERS.get(char_id)
                # Берём ответ одного из других персонажей (первый)
                other_response = responses.get(other_ids[0], "")
                comment_prompt = f"Комментарий к ответу: \"{other_response}\". Ответь в стиле {char['display_name']}, кратко и ёмко."
                future = executor.submit(call_deepseek_api, comment_prompt, [])
                comment = future.result()
                bot.send_message(
                    chat_id=chat_id,
                    text=f"*{char['display_name']}* (комментарий): {comment}",
                    parse_mode=ParseMode.MARKDOWN
                )

# ==================== Команда /clear ====================
def clear_command(update, context):
    """Очищает контекст текущего чата в Supabase."""
    chat_id = update.effective_chat.id
    try:
        supabase.table("messages").delete().eq("chat_id", chat_id).execute()
        update.message.reply_text("Контекст очищен.")
    except Exception as e:
        logger.warning(f"Ошибка при очистке контекста: {e}")
        update.message.reply_text("Ошибка при очистке контекста.")

# ==================== Установка вебхука ====================
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
dispatcher.add_handler(CommandHandler("clear", clear_command))
dispatcher.add_handler(CommandHandler("brainstorm", brainstorm_command))
dispatcher.add_handler(CommandHandler("active", active_command))
dispatcher.add_handler(CommandHandler("dismiss", dismiss_command))
dispatcher.add_handler(CommandHandler("stats", stats_command))
dispatcher.add_handler(CommandHandler("summarize", summarize_command))
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
