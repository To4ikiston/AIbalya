FROM python:3.9-slim

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект в контейнер
COPY . .

# Запускаем приложение с gunicorn, используя переменную окружения PORT
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:$PORT"]
