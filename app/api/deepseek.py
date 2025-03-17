import time
import openai
from app.config import DEEPSEEK_TIMEOUT
from app.utils.formatting import escape_md_v2

def stream_deepseek_api(prompt: str, context_msgs: list):
    messages = [{"role": "system", "content": "Ты – верный слуга Императора, говорящий на языке боевых истин."}]
    if context_msgs:
        context_text = "\n".join(context_msgs)
        messages.append({"role": "system", "content": f"Контекст битвы:\n{context_text}"})
    messages.append({"role": "user", "content": prompt})
    try:
        response = openai.ChatCompletion.create(
            model="deepseek-chat",
            messages=messages,
            stream=True,
            timeout=DEEPSEEK_TIMEOUT
        )
        full_text = ""
        last_update = time.time()
        for chunk in response:
            if 'choices' in chunk and chunk['choices']:
                delta = chunk['choices'][0].get('delta', {})
                text_chunk = delta.get('content', '')
                full_text += text_chunk
                if time.time() - last_update >= 1:
                    yield escape_md_v2(full_text)
                    last_update = time.time()
        yield escape_md_v2(full_text)
    except Exception as e:
        yield escape_md_v2(f"Ошибка DeepSeek: {e}")

def stream_summarize(character_name: str, prompt: str, context_msgs: list):
    messages = [{"role": "system", "content": "Ты – мудрый слуга Императора, суммирующий ход битвы."}]
    if context_msgs:
        context_text = "\n".join(context_msgs)
        messages.append({"role": "system", "content": f"Запись сражения:\n{context_text}"})
    messages.append({"role": "user", "content": prompt})
    try:
        response = openai.ChatCompletion.create(
            model="deepseek-chat",
            messages=messages,
            stream=True,
            timeout=DEEPSEEK_TIMEOUT
        )
        full_text = ""
        last_update = time.time()
        for chunk in response:
            if 'choices' in chunk and chunk['choices']:
                delta = chunk['choices'][0].get('delta', {})
                text_chunk = delta.get('content', '')
                full_text += text_chunk
                if time.time() - last_update >= 1:
                    yield escape_md_v2(full_text)
                    last_update = time.time()
        yield escape_md_v2(full_text)
    except Exception as e:
        yield escape_md_v2(f"Ошибка суммаризации: {e}")
