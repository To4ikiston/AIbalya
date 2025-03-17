from app.db.supabase_client import get_last_messages, save_conversation_history, update_character_state
from app.api.deepseek import stream_summarize
import time

def dismiss_command(update, context):
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or chat_id
    active = context.chat_data.get("active_characters", [])
    if not active:
        update.message.reply_text("Нет призванных воинов для прощания.", parse_mode="MarkdownV2")
        return
    for char in active:
        msgs = get_last_messages(chat_id, thread_id, limit=10)
        prompt = f"Подведи итог битвы и попрощайся в стиле {char}. Учти последние события: {msgs}"
        temp_msg = update.message.reply_text("_Император подводит итог..._", parse_mode="MarkdownV2")
        for generated in stream_summarize(char, prompt, msgs):
            if generated.strip():
                try:
                    context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=temp_msg.message_id,
                        text=f"> *Прощание с {char}:*\n{generated}",
                        parse_mode="MarkdownV2"
                    )
                except Exception as e:
                    time.sleep(1)
        conv = get_last_messages(chat_id, thread_id, limit=100)
        try:
            save_conversation_history(chat_id, thread_id, char, conv)
        except Exception as e:
            logger.warning(f"Ошибка сохранения истории: {e}")
    context.chat_data["active_characters"] = []
