"""
Family Task Tracker — Unified Task Logic
"""

import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
import config
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── States ──────────────────────────────────────────────
(
    T_TITLE,
    T_ASSIGNEE,
    T_DEADLINE,
    T_PRIORITY,
    T_IS_RECURRING,
    T_REC_TYPE,
    T_REC_VALUE
) = range(7)

# ── Helpers ─────────────────────────────────────────────

def format_task_card(task: dict) -> str:
    """Универсальная карточка: понимает и разовые, и регулярные задачи."""
    assignee = task.get("assignee_name") or "—"
    priority_emoji = {1: "🟢", 2: "🟡", 3: "🔥"}.get(task.get("priority", 2), "🟡")
    
    # Проверяем, регулярная ли задача
    is_rec = task.get("is_recurring", False)
    
    if is_rec:
        header = f"🔁 <b>{task['title']}</b> (Регулярная)"
        rtype = task.get("recurrence_type")
        if rtype == "daily": timing = "📅 Ежедневно"
        elif rtype == "weekly": timing = f"📅 Раз в неделю (день {task.get('weekday')})"
        else: timing = f"📅 Раз в {task.get('recurrence_value')} дн."
    else:
        header = f"📌 <b>{task['title']}</b>"
        dl = task.get("deadline")
        timing = f"⏰ До: {dl[:10]}" if dl else "⏰ Без срока"

    return (
        f"{header}\n"
        f"👤 {assignee}\n"
        f"{timing}\n"
        f"{priority_emoji} Приоритет: {task.get('priority', 2)}"
    )

# ── Handlers ────────────────────────────────────────────

@authorized
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все мои задачи", callback_data="list_all")],
        [InlineKeyboardButton("➕ Добавить задачу", callback_data="add_any_task")],
        [InlineKeyboardButton("⚠️ Просроченные", callback_data="overdue")],
    ])
    await update.message.reply_text("Управление задачами:", reply_markup=keyboard)

# ── Unified Creation Flow ───────────────────────────────

async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("✏️ Название задачи:")
    return T_TITLE

async def t_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tmp_task"] = {"title": update.message.text}
    users = db.get_all_users()
    await update.message.reply_text("👤 Кто выполняет?", reply_markup=user_keyboard(users, "assign"))
    return T_ASSIGNEE

async def t_assignee_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["tmp_task"]["assigned_to"] = query.data.split(":")[1]
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Высокий", callback_data="p:3"),
         InlineKeyboardButton("🟡 Средний", callback_data="p:2"),
         InlineKeyboardButton("🟢 Низкий", callback_data="p:1")]
    ])
    await query.edit_message_text("🔥 Приоритет:", reply_markup=kb)
    return T_PRIORITY

async def t_priority_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["tmp_task"]["priority"] = int(query.data.split(":")[1])
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Регулярная", callback_data="rec_yes")],
        [InlineKeyboardButton("📍 Разовая", callback_data="rec_no")]
    ])
    await query.edit_message_text("Тип задачи:", reply_markup=kb)
    return T_IS_RECURRING

async def t_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "rec_no":
        # Сохраняем как обычную
        task_data = context.user_data["tmp_task"]
        db.create_task(
            title=task_data["title"],
            assigned_to=task_data["assigned_to"],
            priority=task_data["priority"],
            is_recurring=False
        )
        await query.edit_message_text("✅ Разовая задача добавлена!")
        return ConversationHandler.END
    else:
        # Переходим к настройке частоты
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Ежедневно", callback_data="rt:daily")],
            [InlineKeyboardButton("Интервал (дни)", callback_data="rt:interval")]
        ])
        await query.edit_message_text("Как часто повторять?", reply_markup=kb)
        return T_REC_TYPE

async def t_rec_type_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rtype = query.data.split(":")[1]
    context.user_data["tmp_task"]["recurrence_type"] = rtype
    
    if rtype == "daily":
        # Сразу сохраняем
        d = context.user_data["tmp_task"]
        db.create_task(
            title=d["title"], assigned_to=d["assigned_to"],
            priority=d["priority"], is_recurring=True, recurrence_type="daily"
        )
        await query.edit_message_text("✅ Ежедневная задача создана!")
        return ConversationHandler.END
    
    await query.edit_message_text("🔢 Через сколько дней повторять?")
    return T_REC_VALUE

async def t_rec_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if not val.isdigit():
        await update.message.reply_text("Введите число.")
        return T_REC_VALUE
    
    d = context.user_data["tmp_task"]
    db.create_task(
        title=d["title"], assigned_to=d["assigned_to"],
        priority=d["priority"], is_recurring=True, 
        recurrence_type="interval", recurrence_value=int(val)
    )
    await update.message.reply_text(f"✅ Регулярная задача (раз в {val} дн.) создана!")
    return ConversationHandler.END

# ── Logic ───────────────────────────────────────────────

@authorized
async def done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    task_id = query.data.split(":")[1]
    task = db.get_task_by_id(task_id)
    
    if task.get("is_recurring"):
        # Если регулярная — просто сдвигаем дату "следующего напоминания"
        db.update_recurring_task_next_date(task_id)
        await query.answer("✅ Отмечено! Задача появится снова согласно графику.")
        await query.edit_message_text(f"✅ {task['title']}: выполнено сегодня.")
    else:
        # Если обычная — закрываем
        db.complete_task(task_id)
        await query.edit_message_text(f"✅ Задача '{task['title']}' завершена!")

# ── Main ────────────────────────────────────────────────

def main():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Единый процесс создания
    task_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_task_start, pattern="^add_any_task$")],
        states={
            T_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, t_title_received)],
            T_ASSIGNEE: [CallbackQueryHandler(t_assignee_received, pattern="^assign:")],
            T_PRIORITY: [CallbackQueryHandler(t_priority_received, pattern="^p:")],
            T_IS_RECURRING: [CallbackQueryHandler(t_type_choice, pattern="^rec_")],
            T_REC_TYPE: [CallbackQueryHandler(t_rec_type_received, pattern="^rt:")],
            T_REC_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, t_rec_value_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    app.add_handler(task_conv)
    app.add_handler(CallbackQueryHandler(done_callback, pattern="^done:"))
    app.add_handler(CallbackQueryHandler(menu_callback)) # Для списков и меню
    
    # Очередь уведомлений теперь одна — она просто берет все актуальные задачи
    app.job_queue.run_repeating(db.check_all_notifications, interval=3600)

    app.run_polling()
