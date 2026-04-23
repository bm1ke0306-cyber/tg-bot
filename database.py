"""
Database module — Supabase client and all DB operations.
"""

from datetime import datetime, timedelta, date
from typing import Optional
from supabase import create_client, Client
import config
import pytz

tz = pytz.timezone(config.BOT_TIMEZONE)

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


# ─── Users ──────────────────────────────────────────────

def get_user_by_telegram_id(telegram_id: int) -> Optional[dict]:
    """Return user dict or None if not in whitelist."""
    res = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    return res.data[0] if res.data else None


def get_all_users() -> list[dict]:
    """Return all whitelisted users."""
    res = supabase.table("users").select("*").execute()
    return res.data


# ─── Tasks ──────────────────────────────────────────────

def create_task(
    title: str,
    assigned_to: str,
    created_by: str,
    deadline: Optional[str] = None,
    priority: int = 2,
    description: Optional[str] = None,
) -> dict:
    """Create a one-time task. Returns the created row."""
    payload = {
        "title": title,
        "assigned_to": assigned_to,
        "created_by": created_by,
        "priority": priority,
        "status": "pending",
        "is_recurring": False,
    }
    if deadline:
        payload["deadline"] = deadline
    if description:
        payload["description"] = description
    res = supabase.table("tasks").insert(payload).execute()
    return res.data[0]


def get_tasks_for_user(user_id: str, status: str = "pending") -> list[dict]:
    """Return pending tasks assigned to a user."""
    res = (
        supabase.table("tasks")
        .select("*, assignee:assigned_to(name), creator:created_by(name)")
        .eq("assigned_to", user_id)
        .eq("status", status)
        .eq("is_recurring", False)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


def get_tasks_today(user_id: str) -> list[dict]:
    """Return tasks with deadline = today for the given user."""
    now = datetime.now(tz)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    day_end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
    res = (
        supabase.table("tasks")
        .select("*, assignee:assigned_to(name), creator:created_by(name)")
        .eq("assigned_to", user_id)
        .eq("status", "pending")
        .eq("is_recurring", False)
        .gte("deadline", day_start)
        .lte("deadline", day_end)
        .order("deadline")
        .execute()
    )
    return res.data


def get_overdue_tasks(user_id: Optional[str] = None) -> list[dict]:
    """Return overdue tasks (deadline < now, status=pending)."""
    now = datetime.now(tz).isoformat()
    query = (
        supabase.table("tasks")
        .select("*, assignee:assigned_to(name), creator:created_by(name)")
        .eq("status", "pending")
        .eq("is_recurring", False)
        .lt("deadline", now)
        .not_.is_("deadline", "null")
    )
    if user_id:
        query = query.eq("assigned_to", user_id)
    res = query.order("deadline").execute()
    return res.data


def complete_task(task_id: str) -> dict:
    """Mark a task as done."""
    now = datetime.now(tz).isoformat()
    res = (
        supabase.table("tasks")
        .update({"status": "done", "completed_at": now})
        .eq("id", task_id)
        .execute()
    )
    return res.data[0] if res.data else {}


def get_task_by_id(task_id: str) -> Optional[dict]:
    res = (
        supabase.table("tasks")
        .select("*, assignee:assigned_to(name), creator:created_by(name)")
        .eq("id", task_id)
        .execute()
    )
    return res.data[0] if res.data else None


# ─── Recurring tasks ───────────────────────────────────

def create_recurring_task(
    title: str,
    assigned_to: str,
    recurrence_type: str,
    recurrence_value: int = 1,
    weekday: Optional[int] = None,
) -> dict:
    payload = {
        "title": title,
        "assigned_to": assigned_to,
        "recurrence_type": recurrence_type,
        "recurrence_value": recurrence_value,
    }
    if weekday is not None:
        payload["weekday"] = weekday
    res = supabase.table("recurring_tasks").insert(payload).execute()
    return res.data[0]


def get_recurring_tasks(user_id: Optional[str] = None) -> list[dict]:
    query = supabase.table("recurring_tasks").select(
        "*, assignee:assigned_to(name)"
    )
    if user_id:
        query = query.eq("assigned_to", user_id)
    res = query.order("created_at", desc=True).execute()
    return res.data


def complete_recurring_task(task_id: str) -> dict:
    now = datetime.now(tz).isoformat()
    res = (
        supabase.table("recurring_tasks")
        .update({"last_completed_at": now})
        .eq("id", task_id)
        .execute()
    )
    return res.data[0] if res.data else {}


def get_active_recurring_tasks() -> list[dict]:
    """Return recurring tasks that are due (need action)."""
    all_tasks = get_recurring_tasks()
    now = datetime.now(tz)
    active = []
    for t in all_tasks:
        if is_recurring_due(t, now):
            active.append(t)
    return active


def is_recurring_due(task: dict, now: Optional[datetime] = None) -> bool:
    """Check if a recurring task is due based on its schedule."""
    if now is None:
        now = datetime.now(tz)

    last = task.get("last_completed_at")
    if last is None:
        return True  # never completed → due

    if isinstance(last, str):
        last = datetime.fromisoformat(last.replace("Z", "+00:00"))
    if last.tzinfo is None:
        last = tz.localize(last)
    else:
        last = last.astimezone(tz)

    rtype = task["recurrence_type"]
    rval = task.get("recurrence_value", 1) or 1

    if rtype == "daily":
        return (now - last) >= timedelta(days=1)
    elif rtype == "interval":
        return (now - last) >= timedelta(days=rval)
    elif rtype == "weekly":
        weekday = task.get("weekday", 0) or 0
        if now.weekday() != weekday:
            return False
        # Check if completed this week already
        return last.date() < now.date()

    return False


def delete_recurring_task(task_id: str):
    supabase.table("recurring_tasks").delete().eq("id", task_id).execute()
