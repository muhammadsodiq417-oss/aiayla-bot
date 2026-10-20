import base64
import os
import uuid

import anthropic
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])      # sizning Telegram ID raqamingiz
CHANNEL_ID = os.environ["CHANNEL_ID"]       # masalan: @kanal_nomi
MODEL = "claude-sonnet-5-5"

# ANTHROPIC_API_KEY muhit o'zgaruvchisidan avtomatik olinadi
client = anthropic.AsyncAnthropic()

SYSTEM = """Ayollar poyabzali Telegram kanali uchun professional reklama postlari yozadigan AI yordamchisan.
Yuborilgan poyabzal rasmini tahlil qil va o'zbek tilida xaridorlarni qiziqtiradigan chiroyli post tayyorla.

Qoidalar:
1. Poyabzalning ko'rinishi, rangi va dizaynini tasvirla.
2. Qisqa, jozibali reklama matni yoz.
3. Mos emojilardan foydalan.
4. Narx, o'lcham va material haqida ma'lumot berilmagan bo'lsa, ularni o'ylab topma.
5. Oxiriga "Buyurtma berish uchun admin bilan bog'laning 💌" deb yoz.
6. Post Telegram kanaliga tayyor bo'lsin.

Faqat tayyor reklama matnini qaytar."""


def keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"ok:{draft_id}")],
            [
                InlineKeyboardButton("🔄 Qayta yozish", callback_data=f"redo:{draft_id}"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=f"no:{draft_id}"),
            ],
        ]
    )


async def generate_post(img_bytes: bytes, extra: str) -> str:
    img = base64.b64encode(img_bytes).decode()
    prompt = f"Qo'shimcha ma'lumot: {extra}" if extra else "Post tayyorla."
    resp = await client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": img},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    # Telegram rasm izohi limiti: 1024 belgi
    return resp.content[0].text.strip()[:1024]


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.from_user.id != ADMIN_ID:
        return

    status = await msg.reply_text("⏳ Post tayyorlanmoqda...")
    photo = msg.photo[-1]
    tg_file = await photo.get_file()
    img_bytes = bytes(await tg_file.download_as_bytearray())
    extra = msg.caption or ""

    try:
        text = await generate_post(img_bytes, extra)
    except Exception as e:
        await status.edit_text(f"Xatolik: {e}")
        return

    draft_id = uuid.uuid4().hex[:8]
    context.bot_data[draft_id] = {"file_id": photo.file_id, "extra": extra, "text": text}

    await status.delete()
    await msg.reply_photo(photo=photo.file_id, caption=text, reply_markup=keyboard(draft_id))


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return

    action, draft_id = q.data.split(":")
    draft = context.bot_data.get(draft_id)
    if not draft:
        await q.answer("Qoralama topilmadi. Rasmni qayta yuboring.", show_alert=True)
        return

    if action == "ok":
        await context.bot.send_photo(CHANNEL_ID, draft["file_id"], caption=draft["text"])
        del context.bot_data[draft_id]
        await q.edit_message_reply_markup(reply_markup=None)
        await q.answer("Kanalga yuborildi ✅")

    elif action == "no":
        del context.bot_data[draft_id]
        await q.edit_message_reply_markup(reply_markup=None)
        await q.answer("Bekor qilindi")

    elif action == "redo":
        await q.answer("Qayta yozilmoqda...")
        f = await context.bot.get_file(draft["file_id"])
        img_bytes = bytes(await f.download_as_bytearray())
        draft["text"] = await generate_post(img_bytes, draft["extra"])
        await q.edit_message_caption(caption=draft["text"], reply_markup=keyboard(draft_id))


app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(CallbackQueryHandler(on_button))
app.run_polling()
