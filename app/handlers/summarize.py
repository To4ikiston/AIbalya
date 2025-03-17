from app.db.supabase_client import get_last_messages
from app.api.deepseek import stream_summarize
import time

def summarize_command(update, context):
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or chat_id
    msgs = get_last_messages(chat_id, thread_id, limit=30)
    prompt = "Сформируй краткий итог боевых действий в стиле Империума."
    temp_msg = update.message.reply_text("_Император суммирует бой..._", parse_mode="MarkdownV2")
    for generated in stream_summarize("Обзор сражения", prompt, msgs):
        if generated.strip():
            try:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=temp_msg.message_id,
                    text=f"*Итог битвы:*\n{generated}",
                    parse_mode="MarkdownV2"
                )
            except Exception as e:
                time.sleep(1)
