from supabase import create_client, Client
from app.config import SUPABASE_URL, SUPABASE_KEY

# Инициализируем клиента
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def insert_message(chat_id: int, thread_id: int, user_id: int, text: str):
    data = {"chat_id": chat_id, "thread_id": thread_id, "user_id": user_id, "text": text}
    return supabase.table("messages").insert(data).execute()

def save_conversation_history(chat_id: int, thread_id: int, active_character: str, conversation: list):
    """
    Сохраняет историю завершённой сессии в таблицу conversation_history.
    """
    conversation_text = "\n".join(conversation)
    data = {
        "chat_id": chat_id,
        "thread_id": thread_id,
        "conversation": conversation_text,
        "active_character": active_character,
        "session_end": "now()"
    }
    return supabase.table("conversation_history").insert(data).execute()


def get_last_messages(chat_id: int, thread_id: int, limit=10):
    res = supabase.table("messages").select("text")\
        .eq("chat_id", chat_id)\
        .eq("thread_id", thread_id)\
        .order("timestamp", desc=True)\
        .limit(limit).execute()
    rows = res.data or []
    rows.reverse()
    return [r["text"] for r in rows]

def update_character_state(chat_id: int, character_id: str):
    """
    Обновляет (увеличивает) счетчик призывов персонажа для данного чата.
    Если записи нет, создаёт новую и возвращает 1, иначе возвращает новое значение счетчика.
    """
    try:
        res = supabase.table("characters_state") \
            .select("*") \
            .eq("chat_id", chat_id) \
            .eq("character_id", character_id) \
            .execute()
        rows = res.data or []
        if not rows:
            data = {"chat_id": chat_id, "character_id": character_id, "summon_count": 1, "last_index": 0}
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
