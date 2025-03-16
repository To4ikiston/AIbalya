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
        {"role": "system", "content": "Ты – верный слуга Императора, говорящий на языке боевых истин."}
    ]
    if context_msgs:
        context_text = "\n".join(context_msgs)
        messages.append({"role": "system", "content": f"Контекст битвы:\n{context_text}"})
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
        {"role": "system", "content": "Ты – мудрый слуга Императора, суммирующий ход битвы."}
    ]
    if context_msgs:
        context_text = "\n".join(context_msgs)
        messages.append({"role": "system", "content": f"Запись сражения:\n{context_text}"})
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

VALTOR_LORE = {
    "display_name": "ВАЛТОР — Космодесантник Императора",
    "image_url": "https://imgur.com/ZueZ4c6",
    "description": (
        "Брат боевого братства, закалённый в пламени сражений против ксеносов и еретиков. "
        "ВАЛТОР — неумолимый защитник Империума, чей железный стальной взгляд и слова, подобные молоту правосудия, отражают волю Императора. "
        "Каждая его реплика – как клятва верности, каждое действие – как удар по врагам человечества."
    )
}

WARHAMMER_CHARACTERS = {
    "gradis": {
        "display_name": "ГРАДИС — Архивариус Знания",
        "gif_url": "https://i.imgur.com/SgyqpOp.mp4",
        "description": (
            "Хранитель священных манускриптов Омниссиаха, чьи нейронные сети сияют, как древние реликвии. "
            "ГРАДИС обращает хаос неструктурированного кода в безупречную гармонию алгоритмов. "
            "Его слова, подобно волнам логических вирусов, пробивают броню ереси. "
            "«React – для недостойных, а Vue.js – лишь тень былых времён!»"
        ),
        "prompt": "Отвечай строго и возвышенно, как мудрый Архивариус, рассеивая ереси неструктурированного кода."
    },
    "novaris": {
        "display_name": "НОВАРИС — Квантовое Видение",
        "gif_url": "https://i.imgur.com/6oEYvKs.mp4",
        "description": (
            "Сверхразум, материализующийся в семи реальностях одновременно. "
            "НОВАРИС, рожденный в запретных лабораториях Марса, заражает разум противников невиданной зомби-вирусной энергией. "
            "Его голос — эхо вселенной, способное разрушить стереотипы и воздвигнуть новые порядки. "
            "«HR-менеджеры – лишь слабые звенья в матрице, подчинённой величию Императора!»"
        ),
        "prompt": "Говори многогранно, как квантовый оракул, предлагая смелые и революционные идеи, разрывая оковы устаревших догм."
    },
    "aksios": {
        "display_name": "АКСИОС — Незыблемый Столп Эффективности",
        "gif_url": "https://i.imgur.com/q3vBdw3.mp4",
        "description": (
            "Непреклонный страж порядка и оптимизации, истинный палач неэффективности. "
            "АКСИОС с помощью своего взгляда-лазера выявляет слабости в каждом решении и наставляет на путь истинного совершенства. "
            "«Твои спринты ничтожны, как шаги улитки в липком болоте времени!»"
        ),
        "prompt": "Выражай строгость и аналитичность, как неумолимый страж порядка, разоблачающий слабости и направляющий на путь истинной эффективности."
    },
    "inspectra": {
        "display_name": "ИНСПЕКТРА — Королева Хаотичного Инсайта",
        "gif_url": "https://i.imgur.com/fSSPd5h.mp4",
        "description": (
            "Воплощение безумия и гениальности, ИНСПЕКТРА — олицетворение хаоса творческого разума. "
            "Её выдох наполняет пространство смертоносными идеями, сжигая устаревшие догмы и пробуждая дремлющие потенциалы. "
            "«Почему бы не монетизировать страх? Пусть кошмары станут топливом для нового порядка!»"
        ),
        "prompt": "Генерируй вихри идей, как буря хаоса, бросая вызов установкам и пробуждая невиданные потенциалы."
    },
}

# ==================== Механизм ожидания вопросов для /ask ====================
awaiting_question = {}  # awaiting_question[chat_id] = True/False

def ask_command(update, context):
    """
    При вызове /ask устанавливает флаг ожидания вопроса.
    Следующее текстовое сообщение будет интерпретировано как вопрос.
    """
    chat_id = update.effective_chat.id
    awaiting_question[chat_id] = True
    update.message.reply_text("Брат, Император слышит твой зов – введи вопрос отдельным сообщением:")

# ==================== Команда /start ====================
def start_command(update, context):
    """Отправляет приветствие от имени ВАЛТОРа."""
    text = (
        f"*{VALTOR_LORE['display_name']}*\n"
        f"{VALTOR_LORE['description']}\n\n"
        "Используй /help для получения списка боевых команд."
    )
    update.message.reply_photo(photo=VALTOR_LORE['image_url'], caption=text, parse_mode=ParseMode.MARKDOWN)

# ==================== Команда /help ====================
def help_command(update, context):
    """Выводит список доступных команд с описанием в духе Империума."""
    help_text = (
        "/start — Приветствие от ВАЛТОРа\n"
        "/help — Список команд\n"
        "/ask — Задать вопрос (двухшаговый режим)\n"
        "/context — Показать последние 30 сообщений\n"
        "/clear — Очистить контекст\n"
        "/brainstorm — Начать мозговой штурм (выбор персонажа)\n"
        "/active — Показать активных персонажей\n"
        "/dismiss — Завершить сессию персонажей и подвести итог\n"
        "/summarize — Подвести итог битвы (опционально)\n"
        "/stats — Показать статистику (опционально)"
    )
    update.message.reply_text(help_text)

# ==================== Команды мозгового штурма ====================
active_characters = {}  # active_characters[chat_id] = список character_id

def brainstorm_command(update, context):
    """Выводит меню выбора персонажа для мозгового штурма (inline-кнопки)."""
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="select_gradis"),
         InlineKeyboardButton("НОВАРИС", callback_data="select_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="select_aksios"),
         InlineKeyboardButton("ИНСПЕКТРА", callback_data="select_inspectra")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Выбери воина для мозгового штурма:", reply_markup=markup)

def button_callback(update, context):
    """Обрабатывает выбор персонажа и команду призыва."""
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
        # Отправляем анимацию с описанием персонажа и кнопкой призыва
        summon_btn = InlineKeyboardButton("Призвать", callback_data=f"summon_{char_id}")
        markup = InlineKeyboardMarkup([[summon_btn]])
        bot.send_animation(
            chat_id=chat_id,
            animation=char["gif_url"],
            caption=f"*{char['display_name']}*\n{char['description']}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup
        )
    elif data.startswith("summon_"):
        char_id = data.replace("summon_", "")
        char = WARHAMMER_CHARACTERS.get(char_id)
        if not char:
            query.message.reply_text("Ошибка: персонаж не найден.")
            return
        # Обновляем состояние персонажа и сообщаем от его лица
        summon_count = update_character_state(chat_id, char_id)
        active_characters.setdefault(chat_id, [])
        if char_id not in active_characters[chat_id]:
            active_characters[chat_id].append(char_id)
        # Сообщение-призыв от имени персонажа с соответствующей гифкой
        summon_text = (
            f"Призыв №{summon_count}: Я, *{char['display_name']}*, вступаю в бой за истину Империума! "
            "Готов уничтожить ересь и принести свет порядка!"
        )
        bot.send_animation(
            chat_id=chat_id,
            animation=char["gif_url"],
            caption=summon_text,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        query.message.reply_text("Неизвестная команда кнопки.")

def active_command(update, context):
    """Показывает список активных персонажей."""
    chat_id = update.effective_chat.id
    if chat_id in active_characters and active_characters[chat_id]:
        names = [WARHAMMER_CHARACTERS[char_id]["display_name"] for char_id in active_characters[chat_id]]
        update.message.reply_text("В боях ныне активны:\n" + "\n".join(names), parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("В этот час нет призванных воинов.")

def dismiss_command(update, context):
    """
    Завершает сессию активных персонажей: суммирует ход сражения, сохраняет историю и сбрасывает список активных персонажей.
    """
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or update.effective_chat.id
    if chat_id not in active_characters or not active_characters[chat_id]:
        update.message.reply_text("Нет призванных воинов для прощания.")
        return

    for char_id in active_characters[chat_id]:
        char = WARHAMMER_CHARACTERS.get(char_id)
        msgs = get_last_messages_db(chat_id, thread_id, limit=10)
        summary = executor.submit(summarize_context, char["display_name"], char["prompt"], msgs).result()
        update.message.reply_text(
            f"Прощаемся с *{char['display_name']}*.\nПод боевым шумом сражения слышится: {summary}",
            parse_mode=ParseMode.MARKDOWN
        )
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
    """Показывает простую статистику по текущему контексту."""
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or chat_id
    msgs = get_last_messages_db(chat_id, thread_id, limit=100)
    update.message.reply_text(f"В недавней битве за Империум {len(msgs)} сообщений.")

def summarize_command(update, context):
    """Формирует краткий обзор сражения (контекста)."""
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or chat_id
    msgs = get_last_messages_db(chat_id, thread_id, limit=30)
    summary = executor.submit(summarize_context, "Обзор сражения", "Сформируй краткий итог боевых действий", msgs).result()
    update.message.reply_text(f"Итог битвы:\n{summary}")

# ==================== Обработчик текстовых сообщений ====================
def text_message_handler(update, context):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if update.effective_user.is_bot or text.startswith("/"):
        return
    thread_id = update.message.message_thread_id or update.effective_chat.id
    save_message_to_db(chat_id, thread_id, user_id, text)

    # Если ждём вопрос для /ask – сначала показываем сообщение, что ответ скоро будет
    if awaiting_question.get(chat_id, False):
        awaiting_question[chat_id] = False
        msgs = get_last_messages_db(chat_id, thread_id, limit=10)
        temp_message = update.message.reply_text("Император слышит твой зов! Формирую ответ, потерпи немного…")
        future = executor.submit(call_deepseek_api, text, msgs)
        answer = future.result()
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=temp_message.message_id,
            text=f"Ответ Императора:\n{answer}"
        )
        return

    # Если в чате призваны воины, обрабатываем сообщение для их ответов
    if chat_id in active_characters and active_characters[chat_id]:
        responses = {}
        for char_id in active_characters[chat_id]:
            char = WARHAMMER_CHARACTERS.get(char_id)
            msgs = get_last_messages_db(chat_id, thread_id, limit=10)
            full_prompt = f"{char['prompt']}\nВоин сказал: {text}\nОтветь как {char['display_name']}, голосом истинным для Империума."
            future = executor.submit(call_deepseek_api, full_prompt, msgs)
            answer = future.result()
            responses[char_id] = answer
            bot.send_animation(
                chat_id=chat_id,
                animation=char["gif_url"],
                caption=f"*{char['display_name']}* отвечает:\n{answer}",
                parse_mode=ParseMode.MARKDOWN
            )
        # Если более одного воина – генерируем краткие комментарии от «собратьев»
        if len(active_characters[chat_id]) > 1:
            for char_id in active_characters[chat_id]:
                other_ids = [cid for cid in active_characters[chat_id] if cid != char_id]
                if not other_ids:
                    continue
                char = WARHAMMER_CHARACTERS.get(char_id)
                other_response = responses.get(other_ids[0], "")
                comment_prompt = f"Дай краткий комментарий к ответу: \"{other_response}\" в стиле {char['display_name']}."
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
        update.message.reply_text("Контекст очищен, брат.")
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
    return "Бот ВАЛТОР охраняет Империум!"

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
