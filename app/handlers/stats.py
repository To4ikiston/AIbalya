from app.db.supabase_client import get_last_messages

def stats_command(update, context):
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id or chat_id
    msgs = get_last_messages(chat_id, thread_id, limit=100)
    update.message.reply_text(f"В недавней битве за Империум {len(msgs)} сообщений.", parse_mode="MarkdownV2")
