"""
Family Task Tracker — Telegram Bot (MVP+)
Main entry point with all handlers.
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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

import config
import database as db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

tz = pytz.timezone(config.BOT_TIMEZONE)

# ── Conversation states ─────────────────────────────────
(
    TASK_TITLE,
    TASK_ASSIGNEE,
    TASK_RECURRENCE_TYPE,    # Новый шаг: выбор типа (нет, ежедневно и т.д.)
    TASK_RECURRENCE_PARAMS,  # Новый шаг: ввод интервала или дня недели
    TASK_DEADLINE_CHOICE,
    TASK_DEADLINE_DATE,
    TASK_PRIORITY,
) = range(7)

(
    REC_TITLE,
    REC_ASSIGNEE,
    REC_TYPE,
    REC_INTERVAL_VALUE,
    REC_WEEKDAY,
) = range(10, 15)

PRIORITY_MAP = {1: "🟢 низкий", 2: "🟡 средний", 3: "🔴 высокий"}
PRIORITY_EMOJI = {1: "🟢", 2: "🟡", 3: "🔥"}
WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
RECURRENCE_LABELS = {
    "daily": "ежедневно",
    "interval": "раз в N дней",
    "weekly": "раз в неделю",
}


# ═══════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════

def authorized(func):
    """Decorator: only allow whitelisted users."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        user = db.get_user_by_telegram_id(tg_id)
        if not user:
            text = "⛔ У вас нет доступа к этому боту."
            if update.callback_query:
                await update.callback_query.answer(text, show_alert=True)
            else:
                await update.effective_message.reply_text(text)
            return ConversationHandler.END
        context.user_data["db_user"] = user
        return await func(update, context)
    return wrapper

def format_task_card(task: dict) -> str:
    """Render a task as a nice text card with recurrence property."""
    assignee_name = "—"
    if isinstance(task.get("assignee"), dict):
        assignee_name = task["assignee"].get("name", "—")
    elif isinstance(task.get("assignee"), list) and task["assignee"]:
        assignee_name = task["assignee"][0].get("name", "—")

    priority_val = task.get("priority", 2)
    priority_emoji = PRIORITY_EMOJI.get(priority_val, "🟡")
    
    # --- Блок признака регулярности ---
    rec_type = task.get("recurrence_type")
    rec_info = ""
    if rec_type:
        label = RECURRENCE_LABELS.get(rec_type, rec_type)
        if rec_type == "interval":
            label = f"раз в {task.get('recurrence_value', 1)} дн."
        elif rec_type == "weekly":
            wd = task.get("weekday", 0)
            label = f"по {WEEKDAY_NAMES[wd]}"
        rec_info = f"\n🔄 <b>Регулярно:</b> {label}"
    # ----------------------------------

    deadline_str = "без срока"
    if task.get("deadline"):
        try:
            dt = datetime.fromisoformat(task["deadline"].replace("Z", "+00:00"))
            deadline_str = dt.strftime("%d %b %Y")
        except Exception:
            deadline_str = str(task["deadline"])

    status_icon = "✅" if task.get("status") == "done" else "📌"

    lines = [
        f"{status_icon} <b>{task['title']}</b>",
        f"👤 {assignee_name}",
        f"⏰ До: {deadline_str}{rec_info}", # Добавляем инфо о повторе здесь
        f"{priority_emoji} Приоритет: {PRIORITY_MAP.get(priority_val, '🟡 средний')}",
    ]
    return "\n".join(lines)

def format_recurring_card(task: dict) -> str:
    assignee_name = "—"
    if isinstance(task.get("assignee"), dict):
        assignee_name = task["assignee"].get("name", "—")
    elif isinstance(task.get("assignee"), list) and task["assignee"]:
        assignee_name = task["assignee"][0].get("name", "—")

    rtype = task.get("recurrence_type", "daily")
    label = RECURRENCE_LABELS.get(rtype, rtype)
    if rtype == "interval":
        label = f"каждые {task.get('recurrence_value', 1)} дн."
    elif rtype == "weekly":
        wd = task.get("weekday", 0) or 0
        label = f"еженедельно ({WEEKDAY_NAMES[wd]})"

    due = db.is_recurring_due(task)
    status = "⚠️ Нужно выполнить" if due else "✅ Выполнено"

    lines = [
        f"🔁 <b>{task['title']}</b>",
        f"👤 {assignee_name}",
        f"📅 {label}",
        f"Статус: {status}",
    ]
    return "\n".join(lines)


def user_keyboard(users: list[dict], prefix: str) -> InlineKeyboardMarkup:
    """Keyboard with user-selection buttons."""
    buttons = [
        [InlineKeyboardButton(u["name"], callback_data=f"{prefix}:{u['id']}")]
        for u in users
    ]
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


# ═══════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════

MAIN_MENU_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("📋 Мои задачи", callback_data="my_tasks")],
    [InlineKeyboardButton("📅 Сегодня", callback_data="today")],
    [InlineKeyboardButton("⚠️ Просроченные", callback_data="overdue")],
    [InlineKeyboardButton("➕ Добавить задачу", callback_data="add_task")],
    [InlineKeyboardButton("🔁 Регулярные задачи", callback_data="recurring_menu")],
])


@authorized
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = context.user_data["db_user"]
    await update.message.reply_text(
        f"Привет, {user['name']}! 👋\nВыбери действие:",
        reply_markup=MAIN_MENU_KB,
    )


@authorized
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Central router for main-menu inline buttons."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        user = context.user_data["db_user"]
        await query.edit_message_text(
            f"Привет, {user['name']}! 👋\nВыбери действие:",
            reply_markup=MAIN_MENU_KB,
        )

    elif data == "my_tasks":
        await show_my_tasks(query, context)

    elif data == "today":
        await show_today(query, context)

    elif data == "overdue":
        await show_overdue(query, context)

    elif data == "recurring_menu":
        await show_recurring_menu(query, context)

    elif data == "recurring_list":
        await show_recurring_list(query, context)


# ═══════════════════════════════════════════════════════
#  TASK VIEWS
# ═══════════════════════════════════════════════════════
#
async def show_my_tasks(query, context):
    user = context.user_data["db_user"]
    tasks = db.get_tasks_for_user(user["id"])
    if not tasks:
        # ... (код обработки пустого списка)
        return

    for t in tasks:
        # Добавляем значок 🔄 к заголовку в карточке, если задача регулярная
        display_task = t.copy()
        if t.get("recurrence_type"):
            display_task["title"] = f"🔄 {t['title']}"
        
        card = format_task_card(display_task)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Выполнено", callback_data=f"done:{t['id']}")]
        ])
        await query.message.reply_text(card, reply_markup=kb, parse_mode="HTML")

    await query.message.reply_text(
        f"Всего задач: {len(tasks)}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
        ]),
    )
    # Delete the original menu message to avoid clutter
    try:
        await query.message.delete()
    except Exception:
        pass

async def show_today(query, context):
    user = context.user_data["db_user"]
    tasks = db.get_tasks_today(user["id"])
    if not tasks:
        await query.edit_message_text(
            "📅 На сегодня задач нет.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
            ]),
        )
        return

    for t in tasks:
        card = format_task_card(t)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Выполнено", callback_data=f"done:{t['id']}")]
        ])
        await query.message.reply_text(card, reply_markup=kb, parse_mode="HTML")

    await query.message.reply_text(
        f"Задач на сегодня: {len(tasks)}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
        ]),
    )
    try:
        await query.message.delete()
    except Exception:
        pass


async def show_overdue(query, context):
    user = context.user_data["db_user"]
    tasks = db.get_overdue_tasks(user["id"])
    if not tasks:
        await query.edit_message_text(
            "✅ Просроченных задач нет!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
            ]),
        )
        return

    for t in tasks:
        card = format_task_card(t)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Выполнено", callback_data=f"done:{t['id']}")]
        ])
        await query.message.reply_text(card, reply_markup=kb, parse_mode="HTML")

    await query.message.reply_text(
        f"⚠️ Просрочено: {len(tasks)}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
        ]),
    )
    try:
        await query.message.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════
#  COMPLETE TASK
# ═══════════════════════════════════════════════════════

@authorized
async def done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = query.data.split(":")[1]
    db.complete_task(task_id)
    await query.edit_message_text("✅ Задача выполнена!")


# ═══════════════════════════════════════════════════════
#  ADD TASK — ConversationHandler
# ═══════════════════════════════════════════════════════

@authorized
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✏️ Введите название задачи:")
    return TASK_TITLE


@authorized
async def task_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_task"] = {"title": update.message.text}
    users = db.get_all_users()
    kb = user_keyboard(users, "assignee")
    await update.message.reply_text("👤 Выберите исполнителя:", reply_markup=kb)
    return TASK_ASSIGNEE


# --- В существующую функцию выбора исполнителя добавляем переход к регулярности ---
@authorized
async def task_assignee_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Создание задачи отменено.")
        return ConversationHandler.END

    user_id = query.data.split(":")[1]
    context.user_data["new_task"]["assigned_to"] = user_id

    # Теперь спрашиваем про регулярность
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Нет (разовая)", callback_data="rt:none")],
        [InlineKeyboardButton("📅 Ежедневно", callback_data="rt:daily")],
        [InlineKeyboardButton("🔢 Раз в N дней", callback_data="rt:interval")],
        [InlineKeyboardButton("📆 Раз в неделю", callback_data="rt:weekly")],
    ])
    await query.edit_message_text("🔄 Сделать задачу регулярной?", reply_markup=kb)
    return TASK_RECURRENCE_TYPE

# --- Новые функции для обработки регулярности ---

@authorized
async def task_recurrence_type_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rtype = query.data.split(":")[1]
    
    if rtype == "none":
        context.user_data["new_task"]["recurrence_type"] = None
        return await _ask_deadline(query) # Переход к дедлайну

    context.user_data["new_task"]["recurrence_type"] = rtype

    if rtype == "daily":
        return await _ask_deadline(query)

    if rtype == "interval":
        await query.edit_message_text("🔢 Введите количество дней (число):")
        return TASK_RECURRENCE_PARAMS

    if rtype == "weekly":
        buttons = [[InlineKeyboardButton(name, callback_data=f"twd:{i}")] 
                   for i, name in enumerate(WEEKDAY_NAMES)]
        await query.edit_message_text("📆 Выберите день недели:", reply_markup=InlineKeyboardMarkup(buttons))
        return TASK_RECURRENCE_PARAMS

@authorized
async def task_recurrence_params_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Обработка текстового ввода для интервала
    if update.message:
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text("❌ Введите число:")
            return TASK_RECURRENCE_PARAMS
        context.user_data["new_task"]["recurrence_value"] = int(text)
        # После ввода текста нам нужно вручную вызвать отправку вопроса про дедлайн
        return await _ask_deadline_message(update)

    # Обработка нажатия кнопки для дня недели
    query = update.callback_query
    await query.answer()
    weekday = int(query.data.split(":")[1])
    context.user_data["new_task"]["weekday"] = weekday
    return await _ask_deadline(query)

# Вспомогательные функции для перехода к следующему шагу
async def _ask_deadline(query):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Выбрать дату", callback_data="dl_date")],
        [InlineKeyboardButton("🚫 Без срока", callback_data="dl_none")],
    ])
    await query.edit_message_text("⏰ Установить первый дедлайн?", reply_markup=kb)
    return TASK_DEADLINE_CHOICE

async def _ask_deadline_message(update):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Выбрать дату", callback_data="dl_date")],
        [InlineKeyboardButton("🚫 Без срока", callback_data="dl_none")],
    ])
    await update.message.reply_text("⏰ Установить первый дедлайн?", reply_markup=kb)
    return TASK_DEADLINE_CHOICE
    
@authorized
async def task_deadline_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        await query.edit_message_text("❌ Создание задачи отменено.")
        return ConversationHandler.END

    if data == "dl_none":
        context.user_data["new_task"]["deadline"] = None
        return await _ask_priority(query)

    if data == "dl_date":
        # Offer quick-pick dates
        now = datetime.now(tz)
        today = now.date()
        tomorrow = today + timedelta(days=1)
        in_3 = today + timedelta(days=3)
        in_7 = today + timedelta(days=7)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"Сегодня ({today.strftime('%d.%m')})", callback_data=f"dlp:{today.isoformat()}")],
            [InlineKeyboardButton(f"Завтра ({tomorrow.strftime('%d.%m')})", callback_data=f"dlp:{tomorrow.isoformat()}")],
            [InlineKeyboardButton(f"Через 3 дня ({in_3.strftime('%d.%m')})", callback_data=f"dlp:{in_3.isoformat()}")],
            [InlineKeyboardButton(f"Через неделю ({in_7.strftime('%d.%m')})", callback_data=f"dlp:{in_7.isoformat()}")],
            [InlineKeyboardButton("✍️ Ввести вручную", callback_data="dl_manual")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
        ])
        await query.edit_message_text("📅 Выберите дату:", reply_markup=kb)
        return TASK_DEADLINE_DATE


@authorized
async def task_deadline_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        await query.edit_message_text("❌ Создание задачи отменено.")
        return ConversationHandler.END

    if data == "dl_manual":
        await query.edit_message_text("📅 Введите дату (ДД.ММ.ГГГГ):")
        return TASK_DEADLINE_DATE

    if data.startswith("dlp:"):
        date_str = data.split(":")[1]
        # Convert to datetime with end of day in local tz
        d = datetime.fromisoformat(date_str)
        deadline = tz.localize(d.replace(hour=23, minute=59, second=59))
        context.user_data["new_task"]["deadline"] = deadline.isoformat()
        return await _ask_priority(query)


@authorized
async def task_deadline_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle manual date text input."""
    text = update.message.text.strip()
    try:
        d = datetime.strptime(text, "%d.%m.%Y")
        deadline = tz.localize(d.replace(hour=23, minute=59, second=59))
        context.user_data["new_task"]["deadline"] = deadline.isoformat()
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите ДД.ММ.ГГГГ:")
        return TASK_DEADLINE_DATE

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Высокий", callback_data="prio:3")],
        [InlineKeyboardButton("🟡 Средний", callback_data="prio:2")],
        [InlineKeyboardButton("🟢 Низкий", callback_data="prio:1")],
    ])
    await update.message.reply_text("🔥 Приоритет:", reply_markup=kb)
    return TASK_PRIORITY


async def _ask_priority(query):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Высокий", callback_data="prio:3")],
        [InlineKeyboardButton("🟡 Средний", callback_data="prio:2")],
        [InlineKeyboardButton("🟢 Низкий", callback_data="prio:1")],
    ])
    await query.edit_message_text("🔥 Приоритет:", reply_markup=kb)
    return TASK_PRIORITY


@authorized
async def task_priority_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    priority = int(query.data.split(":")[1])
    new = context.user_data["new_task"]
    new["priority"] = priority

    user = context.user_data["db_user"]
    task = db.create_task(
        title=new["title"],
        assigned_to=new["assigned_to"],
        created_by=user["id"],
        deadline=new.get("deadline"),
        priority=priority,
    )

    card = format_task_card(task if "assignee" in task else db.get_task_by_id(task["id"]))
    await query.edit_message_text(
        f"✅ Задача создана!\n\n{card}",
        parse_mode="HTML",
    )

    # Notify the assignee
    if new["assigned_to"] != user["id"]:
        assignee = db.get_user_by_telegram_id(0)  # placeholder
        # Actually look up the user properly
        all_users = db.get_all_users()
        for u in all_users:
            if u["id"] == new["assigned_to"]:
                try:
                    full_task = db.get_task_by_id(task["id"])
                    await context.bot.send_message(
                        chat_id=u["telegram_id"],
                        text=f"📬 Новая задача от {user['name']}:\n\n{format_task_card(full_task)}",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify user {u['telegram_id']}: {e}")
                break

    # Show menu again
    await query.message.reply_text(
        "Выберите действие:",
        reply_markup=MAIN_MENU_KB,
    )
    return ConversationHandler.END


@authorized
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("❌ Отменено.")
    else:
        await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Действие отменено.",
        reply_markup=MAIN_MENU_KB,
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════
#  RECURRING TASKS
# ═══════════════════════════════════════════════════════

async def show_recurring_menu(query, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Список", callback_data="recurring_list")],
        [InlineKeyboardButton("➕ Добавить", callback_data="add_recurring")],
        [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")],
    ])
    await query.edit_message_text("🔁 Регулярные задачи:", reply_markup=kb)


async def show_recurring_list(query, context):
    tasks = db.get_recurring_tasks()
    if not tasks:
        await query.edit_message_text(
            "🔁 Регулярных задач нет.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить", callback_data="add_recurring")],
                [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")],
            ]),
        )
        return

    for t in tasks:
        card = format_recurring_card(t)
        buttons = []
        if db.is_recurring_due(t):
            buttons.append([InlineKeyboardButton(
                "✅ Выполнено", callback_data=f"rec_done:{t['id']}"
            )])
        buttons.append([InlineKeyboardButton(
            "🗑 Удалить", callback_data=f"rec_del:{t['id']}"
        )])
        kb = InlineKeyboardMarkup(buttons)
        await query.message.reply_text(card, reply_markup=kb, parse_mode="HTML")

    await query.message.reply_text(
        f"Всего: {len(tasks)}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Меню", callback_data="main_menu")]
        ]),
    )
    try:
        await query.message.delete()
    except Exception:
        pass


@authorized
async def rec_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = query.data.split(":")[1]
    db.complete_recurring_task(task_id)
    await query.edit_message_text("✅ Регулярная задача отмечена выполненной!")


@authorized
async def rec_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = query.data.split(":")[1]
    db.delete_recurring_task(task_id)
    await query.edit_message_text("🗑 Регулярная задача удалена.")


# ── Add recurring ───────────────────────────────────────

@authorized
async def add_recurring_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✏️ Введите название регулярной задачи:")
    return REC_TITLE


@authorized
async def rec_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_rec"] = {"title": update.message.text}
    users = db.get_all_users()
    kb = user_keyboard(users, "rec_assign")
    await update.message.reply_text("👤 Выберите исполнителя:", reply_markup=kb)
    return REC_ASSIGNEE


@authorized
async def rec_assignee_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Отменено.")
        return ConversationHandler.END

    user_id = query.data.split(":")[1]
    context.user_data["new_rec"]["assigned_to"] = user_id

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Ежедневно", callback_data="rtype:daily")],
        [InlineKeyboardButton("🔢 Раз в N дней", callback_data="rtype:interval")],
        [InlineKeyboardButton("📆 Раз в неделю", callback_data="rtype:weekly")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ])
    await query.edit_message_text("🔁 Тип повторения:", reply_markup=kb)
    return REC_TYPE


@authorized
async def rec_type_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        await query.edit_message_text("❌ Отменено.")
        return ConversationHandler.END

    rtype = data.split(":")[1]
    context.user_data["new_rec"]["recurrence_type"] = rtype

    if rtype == "daily":
        return await _save_recurring(query, context)

    if rtype == "interval":
        await query.edit_message_text("🔢 Введите количество дней (число):")
        return REC_INTERVAL_VALUE

    if rtype == "weekly":
        buttons = [
            [InlineKeyboardButton(name, callback_data=f"wd:{i}")]
            for i, name in enumerate(WEEKDAY_NAMES)
        ]
        buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
        kb = InlineKeyboardMarkup(buttons)
        await query.edit_message_text("📆 Выберите день недели:", reply_markup=kb)
        return REC_WEEKDAY


@authorized
async def rec_interval_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Введите положительное число:")
        return REC_INTERVAL_VALUE

    context.user_data["new_rec"]["recurrence_value"] = int(text)
    # Save
    rec = context.user_data["new_rec"]
    task = db.create_recurring_task(
        title=rec["title"],
        assigned_to=rec["assigned_to"],
        recurrence_type=rec["recurrence_type"],
        recurrence_value=rec["recurrence_value"],
    )
    await update.message.reply_text(
        f"✅ Регулярная задача создана: <b>{rec['title']}</b>\n"
        f"🔁 Каждые {rec['recurrence_value']} дн.",
        parse_mode="HTML",
    )
    await update.message.reply_text("Выберите действие:", reply_markup=MAIN_MENU_KB)
    return ConversationHandler.END


@authorized
async def rec_weekday_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        await query.edit_message_text("❌ Отменено.")
        return ConversationHandler.END

    weekday = int(data.split(":")[1])
    context.user_data["new_rec"]["weekday"] = weekday
    return await _save_recurring(query, context)


async def _save_recurring(query, context):
    rec = context.user_data["new_rec"]
    task = db.create_recurring_task(
        title=rec["title"],
        assigned_to=rec["assigned_to"],
        recurrence_type=rec["recurrence_type"],
        recurrence_value=rec.get("recurrence_value", 1),
        weekday=rec.get("weekday"),
    )

    label = RECURRENCE_LABELS.get(rec["recurrence_type"], rec["recurrence_type"])
    if rec["recurrence_type"] == "weekly" and rec.get("weekday") is not None:
        label = f"еженедельно ({WEEKDAY_NAMES[rec['weekday']]})"

    await query.edit_message_text(
        f"✅ Регулярная задача создана!\n"
        f"🔁 <b>{rec['title']}</b>\n"
        f"📅 {label}",
        parse_mode="HTML",
    )
    await query.message.reply_text("Выберите действие:", reply_markup=MAIN_MENU_KB)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════
#  REMINDERS / CRON
# ═══════════════════════════════════════════════════════

async def check_overdue(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled job: notify users about overdue tasks."""
    logger.info("Running overdue check...")
    users = db.get_all_users()
    for user in users:
        tasks = db.get_overdue_tasks(user["id"])
        if not tasks:
            continue
        lines = ["⚠️ <b>Просроченные задачи:</b>\n"]
        for t in tasks:
            lines.append(f"• {t['title']}")
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text="\n".join(lines),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Overdue notify failed for {user['telegram_id']}: {e}")

    # Also check recurring tasks
    active = db.get_active_recurring_tasks()
    for t in active:
        assignee_id = t.get("assigned_to")
        for user in users:
            if user["id"] == assignee_id:
                try:
                    await context.bot.send_message(
                        chat_id=user["telegram_id"],
                        text=f"🔁 Напоминание: <b>{t['title']}</b> ждёт выполнения!",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"Recurring notify failed: {e}")
                break


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # ── Conversation: Add task ──
    add_task_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_task_start, pattern="^add_task$"),
        ],
        states={
            TASK_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, task_title_received),
            ],
            TASK_ASSIGNEE: [
                CallbackQueryHandler(task_assignee_received, pattern="^(assignee:|cancel)"),
            ],
            TASK_DEADLINE_CHOICE: [
                CallbackQueryHandler(task_deadline_choice, pattern="^(dl_|cancel)"),
            ],
            TASK_DEADLINE_DATE: [
                CallbackQueryHandler(task_deadline_date, pattern="^(dlp:|dl_manual|cancel)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, task_deadline_manual),
            ],
            TASK_PRIORITY: [
                CallbackQueryHandler(task_priority_received, pattern="^prio:"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
        per_message=False,
    )

    # ── Conversation: Add recurring task ──
    add_rec_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_recurring_start, pattern="^add_recurring$"),
        ],
        states={
            REC_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rec_title_received),
            ],
            REC_ASSIGNEE: [
                CallbackQueryHandler(rec_assignee_received, pattern="^(rec_assign:|cancel)"),
            ],
            REC_TYPE: [
                CallbackQueryHandler(rec_type_received, pattern="^(rtype:|cancel)"),
            ],
            REC_INTERVAL_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rec_interval_received),
            ],
            REC_WEEKDAY: [
                CallbackQueryHandler(rec_weekday_received, pattern="^(wd:|cancel)"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
        per_message=False,
    )

    # Register handlers (order matters!)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(add_task_conv)
    app.add_handler(add_rec_conv)
    app.add_handler(CallbackQueryHandler(done_callback, pattern="^done:"))
    app.add_handler(CallbackQueryHandler(rec_done_callback, pattern="^rec_done:"))
    app.add_handler(CallbackQueryHandler(rec_del_callback, pattern="^rec_del:"))
    app.add_handler(CallbackQueryHandler(menu_callback))

    # ── Scheduled job: overdue reminders every 8 hours ──
    job_queue = app.job_queue
    job_queue.run_repeating(
        check_overdue,
        interval=28800,  # every 8 hours
        first=60,        # start 1 min after boot
    )

    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
