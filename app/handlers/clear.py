from telegram import ParseMode

def clear_command(update, context):
    # Пример простой реализации команды /clear, которая очищает контекст
    update.message.reply_text("Контекст очищен, брат.", parse_mode="MarkdownV2")
