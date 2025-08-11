import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
import nest_asyncio

API_ID = 28981728
API_HASH = '0bd5d70147496fa1c759a2db217b033a'
BOT_TOKEN = '7671639138:AAE3rEKUzxSfmrDtMOJd-tX4Khe_V25zjwo'  # আপনার বট টোকেন

PHONE, CODE, PASSWORD = range(3)
user_data_store = {}

nest_asyncio.apply()

# Semaphore দিয়ে একসাথে ১০ নাম্বার চেকের অনুমতি দিবো (আপনি চাইলে বাড়াতে পারেন)
semaphore = asyncio.Semaphore(10)

def get_keyboard(user_id):
    user_info = user_data_store.get(user_id, {})
    numbers = user_info.get('numbers', [])
    buttons = [[InlineKeyboardButton(num, callback_data=f"num_{num}")] for num in numbers]
    buttons.append([InlineKeyboardButton("নাম্বার চেক করো", callback_data='check')])
    buttons.append([InlineKeyboardButton("সব মুছুন", callback_data='clear')])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(
        "স্বাগতম!\n\n"
        "প্রথমে /login দিয়ে লগইন করুন।\n"
        "তারপর ফোন নাম্বার পাঠান, যেগুলো চেক করতে চান।\n\n"
        "নিচের বাটনগুলো ব্যবহার করুন।",
        reply_markup=get_keyboard(user_id)
    )

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👉 তোমার ফোন নম্বর পাঠাও (Country code সহ, যেমন +8801xxxxxxxxx):")
    return PHONE

async def login_phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        await client.send_code_request(phone)
    except Exception as e:
        await update.message.reply_text(f"❌ ফোন নম্বর সঠিক নয় বা অন্য সমস্যা: {e}\nআবার চেষ্টা করো।")
        await client.disconnect()
        return ConversationHandler.END

    context.user_data['phone'] = phone
    context.user_data['client'] = client
    await update.message.reply_text("📩 তোমার কাছে যাওয়া কোডটি পাঠাও:")
    return CODE

async def login_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    phone = context.user_data['phone']
    client: TelegramClient = context.user_data['client']

    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        await update.message.reply_text("🔐 ২এফএ পাসওয়ার্ড দিন:")
        return PASSWORD
    except Exception as e:
        await update.message.reply_text(f"❌ লগইনে সমস্যা: {e}\nআবার চেষ্টা করো।")
        await client.disconnect()
        return ConversationHandler.END

    session_str = client.session.save()
    user_id = update.message.from_user.id

    user_data_store[user_id] = {
        'session': session_str,
        'numbers': [],
        'client': client
    }

    await update.message.reply_text("✅ লগইন সফল হয়েছে! এখন নাম্বার পাঠালে চেক করতে পারবে।")
    return ConversationHandler.END

async def login_password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    user_id = update.message.from_user.id
    user_info = user_data_store.get(user_id)
    if not user_info:
        await update.message.reply_text("❌ প্রথমে /login দিয়ে শুরু করো।")
        return ConversationHandler.END

    client = user_info['client']
    try:
        await client.sign_in(password=password)
    except Exception as e:
        await update.message.reply_text(f"❌ পাসওয়ার্ড সঠিক নয়: {e}\nআবার চেষ্টা করো।")
        return ConversationHandler.END

    session_str = client.session.save()
    user_info['session'] = session_str

    await update.message.reply_text("✅ ২এফএ সহ লগইন সফল হয়েছে! এখন নাম্বার পাঠালে চেক করতে পারবে।")
    return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_info = user_data_store.get(user_id)
    if not user_info or 'session' not in user_info:
        await update.message.reply_text("❌ প্রথমে /login দিয়ে লগইন করো।")
        return

    lines = update.message.text.strip().splitlines()
    cleaned = []
    for line in lines:
        num = line.strip().replace("+", "").replace(" ", "")
        if not num.isdigit():
            continue
        if num.startswith("880"):
            cleaned.append("+" + num)
        elif num.startswith("0"):
            cleaned.append("+880" + num[1:])
        elif num.startswith("88"):
            cleaned.append("+" + num)
        else:
            cleaned.append("+" + num)
    cleaned = list(dict.fromkeys(cleaned))

    if not cleaned:
        await update.message.reply_text("⚠️ সঠিক নাম্বার পাইনি। শুধু সংখ্যা পাঠাও।")
        return

    user_info['numbers'] = cleaned
    await update.message.reply_text(
        f"✅ তোমার {len(cleaned)} টি নাম্বার সংরক্ষণ করা হয়েছে।",
        reply_markup=get_keyboard(user_id)
    )

async def check_single_number(client, num):
    async with semaphore:
        try:
            entity = await client.get_entity(num)
            full_name = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
            if not full_name:
                full_name = "নাম পাওয়া যায়নি"
            return (num, full_name, True)
        except Exception:
            return (num, None, False)

async def check_numbers_telethon(client, numbers):
    tasks = [check_single_number(client, num) for num in numbers]
    results = await asyncio.gather(*tasks)
    return results

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    user_info = user_data_store.get(user_id)

    if data == 'check':
        if not user_info or 'numbers' not in user_info or not user_info['numbers']:
            await query.edit_message_text("❌ তুমি কোনো নাম্বার পাঠাও নি।", reply_markup=get_keyboard(user_id))
            return
        if 'client' not in user_info:
            await query.edit_message_text("❌ প্রথমে /login দিয়ে লগইন করো।", reply_markup=get_keyboard(user_id))
            return

        await query.edit_message_text("⏳ নাম্বার যাচাই করা হচ্ছে...", reply_markup=None)
        try:
            results = await check_numbers_telethon(user_info['client'], user_info['numbers'])
            found = []
            not_found = []
            for num, full_name, found_flag in results:
                if found_flag:
                    found.append(f"{num} ➡️ {full_name}")
                else:
                    not_found.append(num)

            msg_parts = []
            if found:
                msg_parts.append("✅ Telegram এ পাওয়া গেছে:\n" + '\n'.join(found))
            if not_found:
                msg_parts.append("❌ Telegram এ পাওয়া যায়নি:\n" + '\n'.join(not_found))

            await query.edit_message_text('\n\n'.join(msg_parts), reply_markup=get_keyboard(user_id))
        except Exception as e:
            await query.edit_message_text(f"❌ চেক করার সময় সমস্যা: {e}", reply_markup=get_keyboard(user_id))

    elif data.startswith('num_'):
        number = data[4:]
        if not user_info or 'client' not in user_info:
            await query.edit_message_text("❌ প্রথমে /login দিয়ে লগইন করো।", reply_markup=get_keyboard(user_id))
            return

        client = user_info['client']
        try:
            entity = await client.get_entity(number)
            full_name = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
            if not full_name:
                full_name = "নাম পাওয়া যায়নি"
            response = f"✅ {number} - Telegram একাউন্ট আছে: {full_name}"
        except:
            response = f"❌ {number} - Telegram এ একাউন্ট পাওয়া যায়নি।"

        if number in user_info.get('numbers', []):
            user_info['numbers'].remove(number)

        await query.edit_message_text(response, reply_markup=get_keyboard(user_id))

    elif data == 'clear':
        if user_info:
            user_info['numbers'] = []
        await query.edit_message_text("✅ সব নাম্বার মুছে ফেলা হয়েছে।", reply_markup=get_keyboard(user_id))

async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ লগইন প্রক্রিয়া বাতিল করা হয়েছে।")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('login', login_start)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone_handler)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_code_handler)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password_handler)],
        },
        fallbacks=[CommandHandler('cancel', login_cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))

    print("🤖 বট চালু হলো...")
    app.run_polling()

if __name__ == '__main__':
    main()
