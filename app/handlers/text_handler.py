from app.db.supabase_client import save_message_to_db, get_last_messages
from app.api.deepseek import stream_deepseek_api
import time

def text_message_handler(update, context):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if update.effective_user.is_bot or text.startswith("/"):
        return
    thread_id = update.message.message_thread_id or chat_id
    save_message_to_db(chat_id, thread_id, user_id, text)
    # Если режим вопроса активен, генерируем ответ Императора
    if context.chat_data.get("awaiting_question"):
        context.chat_data["awaiting_question"] = False
        msgs = get_last_messages(chat_id, thread_id, limit=10)
        temp_message = update.message.reply_text("_Слава Императору! Формирую ответ..._", parse_mode="MarkdownV2")
        for generated in stream_deepseek_api(text, msgs):
            if generated.strip():
                try:
                    context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=temp_message.message_id,
                        text=f"> *Ответ Императора:*\n{generated}",
                        parse_mode="MarkdownV2"
                    )
                except Exception as e:
                    time.sleep(1)
        return
    # Дополнительная логика для диалога с активными персонажами может быть добавлена здесь.
