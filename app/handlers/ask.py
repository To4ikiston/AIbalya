def ask_command(update, context):
    chat_id = update.effective_chat.id
    # Устанавливаем флаг ожидания вопроса
    context.chat_data['awaiting_question'] = True
    update.message.reply_text(
        "*Слава Императору!* Голос твой достиг священных аудио-каналов Империума. Изложи свой вопрос.",
        parse_mode="MarkdownV2"
    )
