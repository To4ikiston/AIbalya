def active_command(update, context):
    chat_id = update.effective_chat.id
    active = context.chat_data.get("active_characters", [])
    if active:
        names = [x for x in active]  # Здесь можно добавить более подробное имя, если требуется
        update.message.reply_text(f"*На поле битвы активны:*\n" + "\n".join(names), parse_mode="MarkdownV2")
    else:
        update.message.reply_text("В этот час нет призванных воинов.", parse_mode="MarkdownV2")
