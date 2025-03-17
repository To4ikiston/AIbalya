from telegram import ParseMode
from app.api.deepseek import stream_deepseek_api
import time

def help_command(update, context):
    chat_id = update.effective_chat.id
    prompt = ("Сгенерируй список заповедей Императора для космодесантника в стиле Warhammer 40k: "
              "/start, /help, /ask, /context, /clear, /brainstorm, /active, /dismiss, /summarize, /stats.")
    temp_msg = update.message.reply_text(
        "_Слушай, воин, вот заповеди Императора..._",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    for generated in stream_deepseek_api(prompt, []):
        if generated.strip():
            try:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=temp_msg.message_id,
                    text=generated,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                time.sleep(1)
