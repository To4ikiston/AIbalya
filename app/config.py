import os

# Получение значений из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY")
APP_URL = os.getenv("APP_URL", "https://your-app.onrender.com")
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "YOUR_SECRET_TOKEN")

# Дополнительные настройки (например, таймауты)
DEEPSEEK_TIMEOUT = 10  # секунд
