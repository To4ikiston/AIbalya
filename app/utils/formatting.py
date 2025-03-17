def escape_md_v2(text: str) -> str:
    """
    Экранирует спецсимволы для MarkdownV2.
    Допустимые спецсимволы: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    escaped = ""
    for char in text:
        if char in escape_chars:
            escaped += "\\" + char
        else:
            escaped += char
    return escaped
