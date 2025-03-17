from telegram import ParseMode
from app.api.deepseek import stream_deepseek_api
from app.config import BOT_TOKEN
from app.utils.formatting import escape_md_v2
import time

def start_command(update, context):
    chat_id = update.effective_chat.id
    from app.config import VALTOR_LORE  # или импортируйте напрямую, если определено в config.py
    prompt = f"Сгенерируй эпичное приветствие от космодесантника в стиле Warhammer 40k, вдохновляющее воина. Используй данные: {VALTOR_LORE['description']}"
    temp_msg = update.message.reply_photo(
        photo=VALTOR_LORE['image_url'],
        caption="*Брат, Император уже зовёт!*\nДля подробностей нажми */help*.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    for generated in stream_deepseek_api(prompt, []):
        if generated.strip():
            try:
                context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=temp_msg.message_id,
                    caption=generated,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                time.sleep(1)
