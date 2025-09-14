import os
import logging
import asyncpg
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.markdown import hbold

from google import generativeai as genai

# -------------------------------------------------
# Config
# -------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # kendi telegram user id’ni buraya koy

# Küfür listesi
BAD_WORDS = ["salak", "aptal", "orospu", "sikerim", "amk", "yarrak"]

# Ban süresi (saniye cinsinden)
BAN_DURATION = 4 * 60 * 60  # 4 saat

# -------------------------------------------------
# Logging
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# Bot & DB
# -------------------------------------------------
bot = Bot(token=TELEGRAM_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
pool: asyncpg.Pool = None

# -------------------------------------------------
# Gemini API
# -------------------------------------------------
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# -------------------------------------------------
# DB Setup
# -------------------------------------------------
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            chat_id BIGINT,
            message_count INT DEFAULT 0,
            last_used TIMESTAMP DEFAULT NOW()
        )
        """)

async def update_stats(user_id: int, chat_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM stats WHERE user_id=$1 AND chat_id=$2", user_id, chat_id
        )
        if row:
            await conn.execute(
                "UPDATE stats SET message_count = message_count + 1, last_used=NOW() WHERE id=$1",
                row["id"]
            )
        else:
            await conn.execute(
                "INSERT INTO stats (user_id, chat_id, message_count) VALUES ($1, $2, 1)",
                user_id, chat_id
            )

# -------------------------------------------------
# Handlers
# -------------------------------------------------

# 1. /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Merhaba! Ben senin asistan botunum 🚀")

# 2. /info (grup/kanal bilgisi)
@dp.message(Command("info"))
async def cmd_info(message: Message):
    try:
        chat = await bot.get_chat(message.chat.id)
        if chat.type in ["group", "supergroup"]:
            count = await bot.get_chat_member_count(message.chat.id)
            await message.answer(f"👥 Bu grupta {hbold(count)} kişi var.")
        elif chat.type == "channel":
            count = await bot.get_chat_member_count(message.chat.id)
            await message.answer(f"📢 Bu kanalda {hbold(count)} abone var.")
        else:
            await message.answer("ℹ️ Bu komut sadece grup veya kanalda çalışır.")
    except Exception as e:
        await message.answer(f"❌ Hata: {e}")

# 3. Küfür filtresi
@dp.message()
async def moderation(message: Message):
    if not message.text:
        return

    lower_text = message.text.lower()
    if any(bad_word in lower_text for bad_word in BAD_WORDS):
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status not in ["administrator", "creator"]:
            try:
                # Mesajı sil
                await bot.delete_message(message.chat.id, message.message_id)

                # Kullanıcıyı 4 saat banla
                until_date = datetime.now() + timedelta(seconds=BAN_DURATION)
                await bot.ban_chat_member(message.chat.id, message.from_user.id, until_date=until_date)

                await message.answer(
                    f"⚠️ {message.from_user.first_name} küfür ettiği için 4 saat banlandı."
                )
            except Exception as e:
                logging.error(f"Ban hatası: {e}")

    # İstatistik güncelle
    await update_stats(message.from_user.id, message.chat.id)

# 4. /edit komutu (sadece admin)
@dp.message(Command("edit"))
async def cmd_edit(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("❌ Bu komut sadece yöneticiler içindir.")

    text = message.text.replace("/edit", "").strip()
    if not text:
        return await message.answer("Lütfen düzenlenecek bir metin girin.")

    try:
        response = model.generate_content(f"Şu yazıyı düzenle, akıcı yap, emoji ekle:\n\n{text}")
        edited_text = response.text
        await bot.send_message(ADMIN_ID, f"📑 Düzenlenmiş metin:\n\n{edited_text}")
    except Exception as e:
        await message.answer(f"❌ Düzenleme hatası: {e}")

# -------------------------------------------------
# Main
# -------------------------------------------------
async def main():
    await init_db()
    logging.info("Bot başlatılıyor...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
