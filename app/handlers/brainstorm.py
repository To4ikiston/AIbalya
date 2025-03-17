from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from app.config import BRAINSTORM_ANIMATION_URL

def brainstorm_command(update, context):
    keyboard = [
        [InlineKeyboardButton("ГРАДИС", callback_data="select_gradis"),
         InlineKeyboardButton("НОВАРИС", callback_data="select_novaris")],
        [InlineKeyboardButton("АКСИОС", callback_data="select_aksios"),
         InlineKeyboardButton("ИНСПЕКТРА", callback_data="select_inspectra")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_animation(
        animation=BRAINSTORM_ANIMATION_URL,
        caption="*Выбери воина для мозгового штурма:*",
        parse_mode="MarkdownV2",
        reply_markup=markup
    )
