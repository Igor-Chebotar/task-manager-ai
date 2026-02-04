# AI Assistant Bot

**Telegram-бот для интеллектуального тайм-менеджмента**

Курсовой проект студента НИУ ВШЭ. Бот принимает сообщения на естественном языке, использует Google Gemini (LLM) для распознавания намерений пользователя и автоматически создаёт события в Google Calendar или задачи в трекере YouGile.

---

##  Основные возможности

- **Распознавание интентов** — бот анализирует текст на естественном языке с помощью Google Gemini Pro и определяет, что именно хочет сделать пользователь: создать событие, поставить задачу или получить информацию.
- **Интеграция с Google Calendar** — автоматическое создание событий в календаре на основе распознанных дат, времени и описания из сообщения.
- **Интеграция с YouGile** — создание и управление задачами в трекере YouGile прямо из Telegram-чата.

---

## Стек технологий

| Компонент | Технология |
|-----------|------------|
| Язык | Python 3.10+ |
| Telegram-фреймворк | aiogram 3.x (асинхронный) |
| База данных | PostgreSQL (SQLAlchemy + asyncpg) |
| LLM | Google Generative AI (Gemini Pro) |

---

## Установка и запуск

### 1. Клонирование репозитория

```bash
git clone https://github.com/your-username/ai-assistant-bot.git
cd ai-assistant-bot
```

### 2. Создание и активация виртуального окружения

**Linux / macOS:**

```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows:**

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка переменных окружения

Переименуйте файл `.env.example` в `.env`:

```bash
cp .env.example .env
```

Откройте `.env` и заполните следующие переменные:

```env
BOT_TOKEN=ваш_токен_telegram_бота
DB_HOST=localhost
DB_USER=ваш_пользователь_бд
DB_PASS=ваш_пароль_бд
DB_NAME=имя_базы_данных
GEMINI_API_KEY=ваш_ключ_google_gemini
YOUGILE_KEY=ваш_ключ_yougile
```

### 5. Запуск бота

```bash
python main.py
```
