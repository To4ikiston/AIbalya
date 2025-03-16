import os
import logging
import openai
import time
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, CallbackQueryHandler, Filters
from supabase import create_client, Client

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
APP_URL = os.getenv("APP_URL", "")  # Например, https://your-app.onrender.com
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "")

# ==================== Инициализация бота и диспетчера ====================
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=4, use_context=True)

# ==================== Настройка DeepSeek через openai ====================
openai.api_key = DEEPSEEK_API_KEY
openai.api_base = "https://api.deepseek.com"

# ==================== Подключение к Supabase ====================
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==================== ThreadPoolExecutor для фоновых задач ====================
executor = ThreadPoolExecutor(max_workers=4)

# ==================== Функция экранирования для HTML ====================
def escape_html(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

# ==================== Функции работы с базой данных ====================
def save_message_to_db(chat_id: int, thread_id: int, user_id: int, text: str):
    try:
        data = {"chat_id": chat_id, "thread_id": thread_id, "user_id": user_id, "text": text}
        supabase.table("messages").insert(data).execute()
    except Exception as e:
        logger.warning(f"Ошибка записи в DB: {e}")

def get_last_messages_db(chat_id: int, thread_id: int, limit=10):
    try:
        res = supabase.table("messages") \
            .select("text") \
            .eq("chat_id", chat_id) \
            .eq("thread_id", thread_id) \
            .order("timestamp", desc=True) \
            .limit(limit).execute()
        rows = res.data or []
        rows.reverse()
        return [r["text"] for r in rows]
    except Exception as e:
        logger.warning(f"Ошибка получения сообщений: {e}")
        return []

def save_conversation_history(chat_id: int, thread_id: int, active_character: str, conversation: list):
    conversation_text = "\n".join(conversation)
    data = {"chat_id": chat_id, "thread_id": thread_id,
            "conversation": conversation_text, "active_character": active_character,
            "session_end": "now()"}
    try:
        supabase.table("conversation_history").insert(data).execute()
        logger.info("История сессии сохранена успешно.")
    except Exception as e:
        logger.warning(f"Ошибка сохранения истории сессии: {e}")

def update_character_state(chat_id: int, character_id: str):
    try:
        res = supabase.table("characters_state") \
            .select("*") \
            .eq("chat_id", chat_id) \
            .eq("character_id", character_id).execute()
        rows = res.data or []
        if not rows:
            data = {"chat_id": chat_id, "character_id": character_id, "summon_count": 1, "last_index": 0}
            supabase.table("characters_state").insert(data).execute()
            return 1
        else:
            row = rows[0]
            new_count = row["summon_count"] + 1
            supabase.table("characters_state").update({"summon_count": new_count}).eq("id", row["id"]).execute()
            return new_count
    except Exception as e:
        logger.warning(f"Ошибка обновления состояния персонажа: {e}")
        return 1

# ==================== Потоковая генерация через DeepSeek API ====================
def stream_deepseek_api(prompt: str, context_msgs: list):
    messages = [{"role": "system", "content": "Ты – верный слуга Императора, говорящий на языке боевых истин."}]
    if context_msgs:
        context_text = "\n".join(context_msgs)
        messages.append({"role": "system", "content": f"Контекст битвы:\n{context_text}"})
    messages.append({"role": "user", "content": prompt})
    try:
        response = openai.ChatCompletion.create(
            model="deepseek-chat",
            messages=messages,
            stream=True,
            timeout=10
        )
        full_text = ""
        last_update = time.time()
        for chunk in response:
            if 'choices' in chunk and chunk['choices']:
                delta = chunk['choices'][0].get('delta', {})
                text_chunk = delta.get('content', '')
                full_text += text_chunk
                current_time = time.time()
                if current_time - last_update >= 1:
                    yield escape_html(full_text)
                    last_update = current_time
        yield escape_html(full_text)
    except Exception as e:
        logger.error(f"DeepSeek API streaming error: {e}")
        yield escape_html(f"Ошибка DeepSeek: {e}")

def stream_summarize(character_name: str, prompt: str, context_msgs: list):
    messages = [{"role": "system", "content": "Ты – мудрый слуга Императора, суммирующий ход битвы."}]
    if context_msgs:
        context_text = "\n".join(context_msgs)
        messages.append({"role": "system", "content": f"Запись сражения:\n{context_text}"})
    messages.append({"role": "user", "content": prompt})
    try:
        response = openai.ChatCompletion.create(
            model="deepseek-chat",
            messages=messages,
            stream=True,
            timeout=10
        )
        full_text = ""
        last_update = time.time()
        for chunk in response:
            if 'choices' in chunk and chunk['choices']:
                delta = chunk['choices'][0].get('delta', {})
                text_chunk = delta.get('content', '')
                full_text += text_chunk
                current_time = time.time()
                if current_time - last_update >= 1:
                    yield escape_html(full_text)
                    last_update = current_time
        yield escape_html(full_text)
    except Exception as e:
        logger.error(f"DeepSeek Summarize streaming error: {e}")
        yield escape_html(f"Ошибка суммаризации: {e}")

# ==================== Лор персонажей и ВАЛТОРа ====================
VALTOR_LORE = {
    "display_name": "ВАЛТОР — Космодесантник Императора",
    "image_url": "https://imgur.com/ZueZ4c6",  # Фото ВАЛТОРа
    "description": (
        "Брат Империума, закалённый в пламени бесконечных сражений с ксеносами и еретиками. "
        "ВАЛТОР – непоколебимый защитник, чей стальной взгляд пробивает тьму хаоса, а его слова – как молоты правосудия. "
        "Он ведёт своих братьев к свету Императора. Для подробностей нажми <b>/help</b> – дух машины услышит тебя!"
    )
}

WARHAMMER_CHARACTERS = {
    "gradis": {
        "display_name": "ГРАДИС — Архивариус Знания",
        "gif_url": "https://i.imgur.com/SgyqpOp.mp4",
        "description": (
            "Хранитель священных манускриптов, библиотека древних тайн. Он обращает хаос кода в священную гармонию. "
            "Изучи его слова, чтобы постичь истину, скрытую в священных текстах."
        ),
        "prompt": "Отвечай строго и возвышенно, как Архивариус, рассеивая ересь неструктурированного кода."
    },
    "novaris": {
        "display_name": "НОВАРИС — Квантовое Видение",
        "gif_url": "https://i.imgur.com/6oEYvKs.mp4",
        "description": (
            "Сверхразум, порождённый в запретных лабораториях Марса. Он разрывает старые догмы и открывает путь к революционным идеям. "
            "Вслушайся в его видения, и перед тобой откроется бесконечное множество возможностей."
        ),
        "prompt": "Говори многогранно, разрывая оковы устаревших догм и воздвигая новый порядок."
    },
    "aksios": {
        "display_name": "АКСИОС — Незыблемый Столп Эффективности",
        "gif_url": "https://i.imgur.com/q3vBdw3.mp4",
        "description": (
            "Непреклонный страж порядка, палач неэффективности. Его взгляд – как молот правосудия, разоблачающий слабости, "
            "а его слова направляют воинов к совершенству. Услышь его строгость!"
        ),
        "prompt": "Излагай с безжалостной строгостью, разоблачая слабости и направляя воинов к совершенству."
    },
    "inspectra": {
        "display_name": "ИНСПЕКТРА — Королева Хаотичного Инсайта",
        "gif_url": "https://i.imgur.com/fSSPd5h.mp4",
        "description": (
            "Воплощение безумия и гениальности, вихрь идей, разрушающий устоявшие порядки и пробуждающий невиданные возможности. "
            "Её слова – как пламя, сжигающее старое и рождающее новое."
        ),
        "prompt": "Генерируй вихри идей, словно буря хаоса, сметая старые порядки и пробуждая новые возможности."
    },
}

# Дополнительная анимация для выбора персонажа для мозгового штурма
BRAINSTORM_ANIMATION_URL = "https://i.imgur.com/yAQ8BWC.gif"

# ==================== Механизм ожидания вопросов ====================
awaiting_question = {}  # awaiting_question[chat_id] = True/False

# ==================== Команда /ask ====================
def ask_command(update, context):
    chat_id = update.effective_chat.id
    awaiting_question[chat_id] = True
    update.message.reply_text(
        "<b>Слава Императору!</b> Голос твой достиг священных аудио-каналов Империума. Изложи свой вопрос.",
        parse_mode=ParseMode.HTML
    )

# ==================== Команда /start ====================
def start_command(update, context):
    chat_id = update.effective_chat.id
    prompt = (
        f"Сгенерируй эпичное приветствие от космодесантника в стиле Warhammer 40k, "
        f"вдохновляющее воина. Используй данные: {VALTOR_LORE['description']}"
    )
    temp_msg = update.message.reply_photo(
        photo=VALTOR_LORE['image_url'],
        caption="<b>Брат, Император уже зовёт!</b><br>Для подробностей нажми <b>/help</b>.",
        parse_mode=ParseMode.HTML
    )
    for generated in stream_deepseek_api(prompt, []):
        if generated.strip():
            try:
                bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=temp_msg.message_id,
                    caption=generated,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning(f"Ошибка редактирования приветствия: {e}")
                time.sleep(1)

# ==================== Команда /help ====================
def help_command(update, context):
    chat_id = update.effective_chat.id
    prompt = (
        "Сгенерируй список заповедей Императора для космодесантника в стиле Warhammer 40k: "
        "/start, /help, /ask, /context, /clear, /brainstorm, /active, /dismiss, /summarize, /stats."
    )
    temp_msg = update.message.reply_text(
        "<i>Слушай, воин, вот заповеди Императора...</i>",
        parse_mode=ParseMode.HTML
    )
    for generated in stream_deepseek_api(prompt, []):
        if generated.strip():
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=temp_msg.message_id,
                    text=generated,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning(f"Ошибка редактирования /help: {e}")
                time.sleep(1)

# ==================== Команды мозгового штурма ====================
active_characters = {}  # active_characters[chat_id] = список character_id

def brainstorm_command(update, context):
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="select_gradis"),
         InlineKeyboardButton("НОВАРИС", callback_data="select_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="select_aksios"),
         InlineKeyboardButton("ИНСПЕКТРА", callback_data="select_inspectra")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_animation(
        animation=BRAINSTORM_ANIMATION_URL,
        caption="<b>Выбери воина для мозгового штурма:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=markup
    )

def button_callback(update, context):
    query = update.callback_query
    data = query.data
    try:
        query.answer()
    except Exception as e:
        logger.warning(f"Ошибка при ответе на callback: {e}")
    chat_id = query.message.chat_id

    if data.startswith("select_"):
        char_id = data.replace("select_", "")
        char = WARHAMMER_CHARACTERS.get(char_id)
        if not char:
            query.message.reply_text("Ошибка: персонаж не найден.")
            return
        summon_btn = InlineKeyboardButton("Призвать", callback_data=f"summon_{char_id}")
        markup = InlineKeyboardMarkup([[summon_btn]])
        bot.send_animation(
            chat_id=chat_id,
            animation=char["gif_url"],
            caption=f"<b>{char['display_name']}</b><br>{char['description']}",
            parse_mode=ParseMode.HTML,
            reply_markup=markup
        )
    elif data.startswith("summon_"):
        char_id = data.replace("summon_", "")
        char = WARHAMMER_CHARACTERS.get(char_id)
        if not char:
            query.message.reply_text("Ошибка: персонаж не найден.")
            return
        summon_count = update_character_state(chat_id, char_id)
        active_characters.setdefault(chat_id, [])
        if char_id not in active_characters[chat_id]:
            active_characters[chat_id].append(char_id)
        prompt = (
            f"Ты только что завершил важное задание. Сгенерируй вступительное послание в стиле Warhammer 40k, "
            f"оповещающее, что ты прибыл на помощь. Используй стиль: {char['prompt']}"
        )
        temp_msg = bot.send_animation(
            chat_id=chat_id,
            animation=char["gif_url"],
            caption="<i>Голос Императора зовёт в бой!</i>",
            parse_mode=ParseMode.HTML
        )
        for generated in stream_deepseek_api(prompt, []):
            if generated.strip():
                try:
                    bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=temp_msg.message_id,
                        caption=f"<b>Призыв №{summon_count}:</b><br>{generated}",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.warning(f"Ошибка редактирования вступительного сообщения: {e}")
                    time.sleep(1)
    else:
        query.message.reply_text("Неизвестная команда кнопки.")

def active_command(update, context):
    chat_id = update.effective_chat.id
    if chat_id in active_characters and active_characters[chat_id]:
        names = [WARHAMMER_CHARACTERS[char_id]["display_name"] for char_id in active_characters[chat_id]]
        update.message.reply_text(f"<b>На поле битвы активны:</b><br>{'<br>'.join(names)}", parse_mode=ParseMode.HTML)
    else:
        update.message.reply_text("В этот час нет призванных воинов.")

def dismiss_command(update, context):
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or update.effective_chat.id
    if chat_id not in active_characters or not active_characters[chat_id]:
        update.message.reply_text("Нет призванных воинов для прощания.")
        return

    for char_id in active_characters[chat_id]:
        char = WARHAMMER_CHARACTERS.get(char_id)
        msgs = get_last_messages_db(chat_id, thread_id, limit=10)
        prompt = f"Подведи итог битвы и попрощайся в стиле {char['display_name']}. Учти последние события: {msgs}"
        temp_msg = update.message.reply_text("<i>Император подводит итог...</i>", parse_mode=ParseMode.HTML)
        for generated in stream_summarize(char["display_name"], prompt, msgs):
            if generated.strip():
                try:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=temp_msg.message_id,
                        text=f"<blockquote>Прощание с <b>{char['display_name']}</b>:<br>{generated}</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.warning(f"Ошибка редактирования итогового сообщения: {e}")
                    time.sleep(1)
        conv = get_last_messages_db(chat_id, thread_id, limit=100)
        try:
            data = {"chat_id": chat_id, "thread_id": thread_id,
                    "conversation": "\n".join(conv),
                    "active_character": char["display_name"]}
            supabase.table("conversation_history").insert(data).execute()
            logger.info("История сессии сохранена.")
        except Exception as e:
            logger.warning(f"Ошибка сохранения истории сессии: {e}")
    active_characters[chat_id] = []

def stats_command(update, context):
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or chat_id
    msgs = get_last_messages_db(chat_id, thread_id, limit=100)
    update.message.reply_text(f"В недавней битве за Империум {len(msgs)} сообщений.")

def summarize_command(update, context):
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or chat_id
    msgs = get_last_messages_db(chat_id, thread_id, limit=30)
    prompt = "Сформируй краткий итог боевых действий в стиле Империума."
    temp_msg = update.message.reply_text("<i>Император суммирует бой...</i>", parse_mode=ParseMode.HTML)
    for generated in stream_summarize("Обзор сражения", prompt, msgs):
        if generated.strip():
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=temp_msg.message_id,
                    text=f"<b>Итог битвы:</b><br>{generated}",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning(f"Ошибка редактирования итогового сообщения: {e}")
                time.sleep(1)

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
        msgs = get_last_messages_db(chat_id, thread_id, limit=10)
        temp_message = update.message.reply_text("<i>Слава Императору! Формирую ответ...</i>", parse_mode=ParseMode.HTML)
        for generated in stream_deepseek_api(text, msgs):
            if generated.strip():
                try:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=temp_message.message_id,
                        text=f"<blockquote>Ответ Императора:<br>{generated}</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.warning(f"Ошибка редактирования ответа: {e}")
                    time.sleep(1)
        return

    if chat_id in active_characters and active_characters[chat_id]:
        responses = {}
        for char_id in active_characters[chat_id]:
            char = WARHAMMER_CHARACTERS.get(char_id)
            msgs = get_last_messages_db(chat_id, thread_id, limit=10)
            full_prompt = f"{char['prompt']}\nВоин сказал: {text}\nОтветь как {char['display_name']}, голосом истинным для Империума."
            temp = bot.send_message(chat_id=chat_id, text="<i>Император направляет голос битвы...</i>", parse_mode=ParseMode.HTML)
            full_response = ""
            for generated in stream_deepseek_api(full_prompt, msgs):
                full_response = generated
                try:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=temp.message_id,
                        text=f"<b>{char['display_name']}</b> отвечает:<br>{generated}",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.warning(f"Ошибка редактирования ответа в битве: {e}")
                    time.sleep(1)
            responses[char_id] = full_response
        if len(active_characters[chat_id]) > 1:
            for char_id in active_characters[chat_id]:
                other_ids = [cid for cid in active_characters[chat_id] if cid != char_id]
                if not other_ids:
                    continue
                char = WARHAMMER_CHARACTERS.get(char_id)
                other_response = responses.get(other_ids[0], "")
                comment_prompt = f"Дай краткий комментарий к ответу: \"{other_response}\" в стиле {char['display_name']}."
                temp = bot.send_message(chat_id=chat_id, text="<i>Император добавляет слово...</i>", parse_mode=ParseMode.HTML)
                for generated in stream_deepseek_api(comment_prompt, []):
                    if generated.strip():
                        try:
                            bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=temp.message_id,
                                text=f"<blockquote><b>{char['display_name']}</b> (комментарий):<br>{generated}</blockquote>",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception as e:
                            logger.warning(f"Ошибка редактирования комментария: {e}")
                            time.sleep(1)

# ==================== Команда /clear ====================
def clear_command(update, context):
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
    "\n".join(get_last_messages_db(update.effective_chat.id,
                                     update.message.message_thread_id or update.effective_chat.id, limit=30))
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
    return "Брат, Император охраняет Империум!"

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
