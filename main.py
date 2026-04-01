import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from config import settings
from services.llm_engine import LLMEngine

logging.basicConfig(level=logging.INFO)
bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()
llm_service = LLMEngine()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("Привет! Я ИИ-ассистент. Напиши задачу, и я ее обработаю.")

@dp.message()
async def handle_message(message: types.Message):
    status_msg = await message.answer("⏳ Анализирую запрос...")
    data = await llm_service.analyze_text(message.text)
    
    if not data:
        await status_msg.edit_text("❌ Не удалось распознать команду.")
        return

    intent = data.get('intent')
    title = data.get('title')
    
    if intent == 'create_event':
        await status_msg.edit_text(f"📅 Запланирована встреча: {title}")
    elif intent == 'create_task':
        await status_msg.edit_text(f"✅ Создаю задачу в YouGile: {title}")
    else:
        await status_msg.edit_text("⚠️ Неизвестный тип задачи.")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")
