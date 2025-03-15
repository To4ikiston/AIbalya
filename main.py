import os
import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")

# Инициализация бота
application = Application.builder().token(BOT_TOKEN).build()

# Хранилище контекста (в памяти)
context_storage = {}

# Конфигурация ролей мозгового штурма
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


# ========== Обработчики команд ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Привет! Я ВАЛТОР - ваш цифровой помощник.\n"
        "Используйте /help для списка команд"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📋 Доступные команды:\n"
        "/start - Начало работы\n"
        "/help - Эта справка\n"
        "/brainstorm - Мозговой штурм\n"
        "/context - Показать историю\n"
        "/clear - Очистить историю\n\n"
        "Просто напишите @VALTOR в любом сообщении чтобы активировать бота!"
    )
    await update.message.reply_text(help_text)

async def brainstorm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(role["name"], callback_data=f"mode_{key}")]
        for key, role in BRAINSTORM_ROLES.items()
    ]
    await update.message.reply_text(
        "🔍 Выберите режим работы:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    history = "\n".join(context_storage.get(chat_id, ["История пуста"]))
    await update.message.reply_text(f"📜 История чата:\n{history}")

async def clear_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    context_storage[chat_id] = []
    await update.message.reply_text("🧹 История очищена!")

# ========== Обработчики сообщений ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text
    
    # Сохраняем сообщение в историю
    if chat_id not in context_storage:
        context_storage[chat_id] = []
    context_storage[chat_id].append(text[:500])  # Ограничение длины
    
    # Реакция на упоминание
    if "@valtor" in text.lower():
        await update.message.reply_text(
            "✅ ВАЛТОР активирован! Используйте /brainstorm для начала работы",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Старт", callback_data="mode_novaris")]])
        )

# ========== Inline-обработчики ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("mode_"):
        mode = query.data[5:]
        role = BRAINSTORM_ROLES.get(mode)
        
        if role:
            response = (
                f"⚡ Активирован режим: {role['name']}\n"
                f"📝 {role['prompt']}\n\n"
                "Отправьте ваш запрос для анализа!"
            )
            await query.edit_message_text(response)
        else:
            await query.edit_message_text("❌ Режим не найден")

# ========== Вебхук и запуск ==========
@app.post('/webhook')
async def webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET_TOKEN:
        return "Unauthorized", 401
    
    json_data = await request.get_json()
    update = Update.de_json(json_data, application.bot)
    await application.process_update(update)
    return 'ok', 200

@app.get('/')
def health_check():
    return "🤖 Бот ВАЛТОР в активном режиме", 200

# Регистрация обработчиков
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("brainstorm", brainstorm))
application.add_handler(CommandHandler("context", handle_context))
application.add_handler(CommandHandler("clear", clear_context))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(MessageHandler(None, handle_message))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))
