# 👨‍👩‍👧‍👦 Family Task Tracker — Telegram Bot

Семейный трекер задач в Telegram: создание, назначение, контроль и напоминания.

## Возможности

- **Разовые задачи** — с дедлайном, приоритетом и исполнителем
- **Регулярные задачи** — ежедневно / раз в N дней / еженедельно
- **Авторизация** — по Telegram ID (whitelist)
- **Уведомления** — о новых задачах и просрочках (каждые 2 часа)
- **Inline-кнопки** — минимум ввода текста

## Структура проекта

```
family-task-bot/
├── bot.py                # Основной файл бота
├── config.py             # Конфигурация (env-переменные)
├── database.py           # Работа с Supabase (CRUD)
├── supabase_schema.sql   # SQL-схема для Supabase
├── requirements.txt      # Python-зависимости
├── .env.example          # Шаблон переменных окружения
└── README.md
```

## Быстрый старт

### 1. Создать бота в Telegram

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot` и следуйте инструкциям
3. Скопируйте токен бота

### 2. Настроить Supabase

1. Создайте проект на [supabase.com](https://supabase.com)
2. Откройте **SQL Editor** и выполните содержимое `supabase_schema.sql`
3. Добавьте пользователей (раскомментируйте INSERT в конце SQL-файла):
   ```sql
   INSERT INTO users (telegram_id, name) VALUES
     (123456789, 'Папа'),
     (987654321, 'Мама'),
     (111111111, 'Лёва'),
     (222222222, 'Мила');
   ```
   > **Как узнать Telegram ID?** Отправьте сообщение боту [@userinfobot](https://t.me/userinfobot)
4. Скопируйте **Project URL** и **anon key** из Settings → API

### 3. Настроить переменные окружения

```bash
cp .env.example .env
```

Заполните `.env`:
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOi...
BOT_TIMEZONE=Asia/Tashkent
```

### 4. Установить зависимости и запустить

```bash
pip install -r requirements.txt
python bot.py
```

## Команды бота

| Команда    | Описание           |
|------------|--------------------|
| `/start`   | Главное меню       |
| `/menu`    | Главное меню       |
| `/cancel`  | Отмена текущего действия |

## Главное меню

```
📋 Мои задачи       — список активных задач
📅 Сегодня          — задачи с дедлайном на сегодня
⚠️ Просроченные     — просроченные задачи
➕ Добавить задачу   — пошаговое создание задачи
🔁 Регулярные задачи — управление регулярными задачами
```

## Как работают регулярные задачи

| Тип          | Логика                                                  |
|--------------|--------------------------------------------------------|
| Ежедневно    | Считается невыполненной, если прошло ≥ 1 день          |
| Раз в N дней | Считается невыполненной, если прошло ≥ N дней          |
| Еженедельно  | Активна в назначенный день недели, если не выполнена   |

## Напоминания

Бот автоматически проверяет просроченные задачи **каждые 2 часа** и отправляет уведомления исполнителям.

## Деплой

### Вариант 1: VPS / сервер

```bash
# Через systemd
sudo nano /etc/systemd/system/family-bot.service
```

```ini
[Unit]
Description=Family Task Tracker Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/family-task-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/family-task-bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable family-bot
sudo systemctl start family-bot
```

### Вариант 2: Railway / Render / Fly.io

1. Загрузите проект в Git-репозиторий
2. Подключите к Railway/Render
3. Добавьте переменные окружения в настройках платформы
4. Деплой произойдёт автоматически

### Вариант 3: Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

```bash
docker build -t family-bot .
docker run -d --env-file .env --name family-bot family-bot
```

## Ограничения MVP

- ❌ Без фото и вложений
- ❌ Без ролей и прав
- ❌ Без истории изменений
- ❌ Без геймификации
- ❌ Без сложных фильтров

## Возможные улучшения

- 🏆 Баллы и награды за выполнение
- 📊 Аналитика по задачам
- 🗣 Голосовой ввод
- 📆 Интеграция с Google Calendar
- ✔️ Подтверждение выполнения создателем задачи
