import os
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import asyncpg
import google.generativeai as genai

# --- Ayarlar ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # railway environment variable
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # kendi telegram user id
DB_URL = os.getenv("DATABASE_URL")  # railway postgres url
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini ayarı
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-pro")

# Bot
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Bot hafızası (sabit bilgi)
bilgi = {
    "bot_isim": "Akıllı Bot",
    "amac": "Sorulara yanıt vermek ve yardımcı olmak.",
    "creator": "Telnarr"
}

# --- PostgreSQL ---
async def init_db():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS stats (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        chat_id BIGINT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    await conn.close()

async def update_stats(user_id, chat_id):
    conn = await asyncpg.connect(DB_URL)
    await conn.execute(
        "INSERT INTO stats(user_id, chat_id) VALUES($1, $2)",
        user_id, chat_id
    )
    await conn.close()

async def get_stats():
    conn = await asyncpg.connect(DB_URL)
    total_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM stats")
    daily = await conn.fetch("""
        SELECT DATE(created_at) as day, COUNT(*) as cnt
        FROM stats
        GROUP BY day
        ORDER BY day DESC
        LIMIT 7
    """)
    await conn.close()
    return total_users, daily

# --- Mesajlar ---
@dp.message(Command("start"))
async def start(message: types.Message):
    await update_stats(message.from_user.id, message.chat.id)
    await message.answer("Merhaba! Ben bir soru-cevap botuyum. Sorunu yaz, sana yardımcı olayım 😊")

@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Bu komutu sadece admin kullanabilir.")
    
    total_users, daily = await get_stats()
    msg = f"📊 Bot İstatistikleri:\n\nToplam Kullanıcı: {total_users}\n"
    msg += "Günlük Kullanım:\n"
    for row in daily:
        msg += f"  {row['day']}: {row['cnt']}\n"
    await message.answer(msg)

@dp.message()
async def handle_message(message: types.Message):
    if message.chat.type in ["group", "supergroup"]:
        me = await bot.get_me()
        if not (message.text and f"@{me.username}" in message.text):
            return  # mention edilmemişse cevap verme
    
    await update_stats(message.from_user.id, message.chat.id)

    # Botun hafızasındaki bilgileri prompt'a ekleyelim
    prompt = f"""
    Sen bir Telegram botusun. Elinde şu bilgiler var: {bilgi}.
    Kullanıcı şu soruyu soruyor: {message.text}
    Lütfen buna göre cevap ver.
    """
    try:
        response = model.generate_content(prompt)
        await message.reply(response.text)
    except Exception as e:
        await message.reply("Üzgünüm, bir hata oluştu. 😢")
        print(e)

# --- Çalıştır ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
