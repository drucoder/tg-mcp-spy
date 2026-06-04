from mcp.server.fastmcp import FastMCP
from datetime import datetime, timezone, timedelta

from db import (
    init_db,
    add_channel,
    remove_channel,
    list_channels,
    get_channel,
    save_posts,
    get_oldest_post_date,
    get_posts,
)
from tg_parser import fetch_page, parse_posts

mcp = FastMCP("Telegram Watcher", json_response=True)

init_db()


@mcp.tool()
def add_channel_tool(channelname: str) -> str:
    """Добавить Telegram-канал в список отслеживания"""
    channelname = channelname.strip().lower().lstrip("@")
    channel = add_channel(channelname)

    return f"Канал @{channel['channelname']} добавлен"


@mcp.tool()
def remove_channel_tool(channelname: str) -> str:
    """Удалить Telegram-канал из списка отслеживания"""
    channelname = channelname.strip().lower().lstrip("@")

    if remove_channel(channelname):
        return f"Канал @{channelname} удалён"

    return f"Канал @{channelname} не найден"


@mcp.tool()
def list_channels_tool() -> str:
    """Показать список отслеживаемых Telegram-каналов"""
    channels = list_channels()

    if not channels:
        return "Нет отслеживаемых каналов"

    lines = [f"@{c['channelname']} (добавлен {c['added_at']})" for c in channels]

    return "\n".join(lines)


@mcp.tool()
def query_posts(
    channels: list[str] | None = None,
    days: int = 1,
) -> str:
    """Найти посты за последние N дней.
    Данные автоматически обновляются с t.me перед поиском.
    Если каналы не указаны — берутся все сохранённые.
    """
    target = []

    if channels:
        for ch in channels:
            ch = ch.strip().lower().lstrip("@")
            row = get_channel(ch)
            if row:
                target.append(row)
            else:
                return f"Канал @{ch} не отслеживается. Сначала добавьте его через add_channel."
    else:
        target = list_channels()

    if not target:
        return "Нет отслеживаемых каналов. Сначала добавьте канал через add_channel."

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    for ch in target:
        channel_id = ch["id"]
        channelname = ch["channelname"]
        before = None

        for _ in range(10):
            if before is not None:
                oldest = get_oldest_post_date(channel_id)
                if oldest and oldest < cutoff:
                    break

            try:
                html = fetch_page(channelname, before)
            except Exception:
                break

            posts = parse_posts(html)
            if not posts:
                break

            save_posts(channel_id, posts)

            if posts[-1]["date"] < cutoff:
                break

            before = posts[-1]["tg_post_id"]

    result = get_posts([c["id"] for c in target], cutoff)

    if not result:
        days_label = "день" if days == 1 else "дня" if days < 5 else "дней"
        return f"Нет постов за последние {days} {days_label}"

    by_ch: dict[str, list[dict]] = {}

    for p in result:
        by_ch.setdefault(p["channelname"], []).append(p)

    parts = []

    for channelname, posts in by_ch.items():
        parts.append(f"\n📢 @{channelname} ({len(posts)}):")

        for p in posts:
            preview = (p["text"][:200] + "…") if len(p["text"]) > 200 else p["text"]
            parts.append(f"[{p['date']}] {preview}")

    return "\n".join(parts)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
