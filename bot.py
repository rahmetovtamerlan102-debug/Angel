#!/usr/bin/env python3
import sqlite3
import re
import subprocess
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

TOKEN = "8736860753:AAFsifvLNmbVDCSkWX-g9KibvGG5WGqtsyQ"
DB_PATH = "/data/data/com.termux/files/home/telegram.db"
DATA_DIR = "/data/data/com.termux/files/home/rod_data"

# ------------------------------------------------------------------
# 1. ПОИСК В SQLite (юзернейм -> телефон)
# ------------------------------------------------------------------
def search_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, phone FROM users WHERE LOWER(username) = LOWER(?)", (username,))
    row = c.fetchone()
    conn.close()
    return row

# ------------------------------------------------------------------
# 2. ПОИСК ПО НОМЕРУ (в трёх таблицах)
# ------------------------------------------------------------------
def search_by_phone(phone):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # users (Telegram)
    c.execute("SELECT username, phone FROM users WHERE phone LIKE ?", (f'%{phone}%',))
    users = c.fetchall()
    # ufa_delivery
    c.execute("SELECT first_name, phone_number, address_city, address_street, address_house FROM ufa_delivery WHERE phone_number = ?", (phone,))
    delivery = c.fetchall()
    # bank_clients
    c.execute("SELECT last_name, first_name, middle_name, phone, address FROM bank_clients WHERE phone = ?", (phone,))
    bank = c.fetchall()
    conn.close()
    return users, delivery, bank

# ------------------------------------------------------------------
# 3. УДАЛЕНИЕ СООБЩЕНИЙ
# ------------------------------------------------------------------
async def delete_after(delay, msg, user_msg=None, prompt_msg=None):
    await asyncio.sleep(delay)
    try:
        if msg:
            await msg.delete()
        if user_msg:
            await user_msg.delete()
        if prompt_msg:
            await prompt_msg.delete()
    except:
        pass

# ------------------------------------------------------------------
# 4. ОБРАБОТЧИКИ КОМАНД
# ------------------------------------------------------------------
async def start(update: Update, context):
    keyboard = [
        [InlineKeyboardButton("👤 Поиск по фио", callback_data="fio")],
        [InlineKeyboardButton("📞 Поиск по номеру", callback_data="phone")],
        [InlineKeyboardButton("🔍 Поиск по юзу", callback_data="username")],
    ]
    await update.message.reply_text(
        f"🔍 Бот поиска\nВаш ID: {update.effective_user.id}\n\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    context.user_data['mode'] = query.data
    if query.data == "fio":
        prompt_msg = await query.message.reply_text("👤 Введи ФИО:")
    elif query.data == "phone":
        prompt_msg = await query.message.reply_text("📞 Введи номер телефона:")
    elif query.data == "username":
        prompt_msg = await query.message.reply_text("🔍 Введи ЮЗ:")
    context.user_data['prompt_msg'] = prompt_msg

# ------------------------------------------------------------------
# 5. ОСНОВНОЙ ПОИСК
# ------------------------------------------------------------------
async def search(update: Update, context):
    mode = context.user_data.get('mode')
    prompt_msg = context.user_data.get('prompt_msg')
    if not mode:
        await update.message.reply_text("Нажми /start")
        return
    request = update.message.text.strip()
    if not request:
        return

    user_msg = update.message
    msg = await update.message.reply_text("🔎 Ищу...")
    asyncio.create_task(delete_after(0, msg, user_msg, prompt_msg))
    context.user_data['mode'] = None
    context.user_data['prompt_msg'] = None

    # --- ПОИСК ПО ЮЗЕРНЕЙМУ ---
    if mode == "username":
        clean = request.lstrip('@').lower()
        row = search_user_by_username(clean)
        if row:
            username, phone = row
            phone_display = phone if phone else "❌ номер отсутствует"
            await update.message.reply_text(f"✅ **Найдено:**\n👤 ЮЗ: @{username}\n📞 Телефон: {phone_display}", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Не найдено")
        return

    # --- ПОИСК ПО НОМЕРУ ---
    if mode == "phone":
        clean = re.sub(r'[\+\-\s\(\)]', '', request)
        if len(clean) == 11 and clean[0] == '8':
            clean = '7' + clean[1:]
        phone_full = '+' + clean

        users, delivery, bank = search_by_phone(phone_full)
        found = False
        text = ""

        if users:
            for u in users[:5]:
                phone_display = u[1] if u[1] else "❌ номер отсутствует"
                text += f"👤 ЮЗ: @{u[0]}\n📞 Телефон: {phone_display}\n\n"
            found = True
        if delivery:
            for d in delivery[:5]:
                text += f"👤 Имя: {d[0] or '—'}\n📞 Номер: {d[1]}\n📍 Адрес: {d[2]} {d[3]} {d[4]}\n\n"
            found = True
        if bank:
            for b in bank[:5]:
                full_name = f"{b[0]} {b[1]} {b[2]}".strip()
                text += f"👤 Клиент: {full_name}\n📞 Номер: {b[3]}\n📍 Адрес: {b[4]}\n\n"
            found = True

        if found:
            await update.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Не найдено")
        return

    # --- ПОИСК ПО ФИО (grep) ---
    if mode == "fio":
        cmd = f'grep -i -m 15 "{request}" {DATA_DIR}/*.txt 2>/dev/null'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if result.stdout:
            lines = result.stdout.strip().split('\n')
            output = "\n".join(lines[:15])
            await update.message.reply_text(f"✅ **Найдено:**\n```{output[:3000]}```", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Не найдено")
        return

    await update.message.reply_text("❌ Не найдено")

# ------------------------------------------------------------------
# 6. ЗАПУСК
# ------------------------------------------------------------------
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))
    print("✅ Бот запущен. Нажми /start в Telegram")
    app.run_polling()

if __name__ == "__main__":
    main()
