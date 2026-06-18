from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base
from mcp.types import (
    ResourceTemplateReference,
    PromptReference,
    Completion,
    CompletionArgument,
    EmbeddedResource,
    TextResourceContents,
)
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


@mcp.resource("tg://channels")
def channels_resource() -> str:
    """Список отслеживаемых Telegram-каналов"""
    channels = list_channels()

    if not channels:
        return "Нет отслеживаемых каналов"

    lines = [f"@{c['channelname']} (добавлен {c['added_at']})" for c in channels]

    return "\n".join(lines)


@mcp.resource("tg://channel/{name}")
def channel_resource(name: str) -> str:
    """Информация об указанном Telegram-канале"""
    name = name.strip().lower().lstrip("@")
    channel = get_channel(name)

    if not channel:
        return f"Канал @{name} не найден"

    return f"@{channel['channelname']} (добавлен {channel['added_at']})"


@mcp.resource("tg://channel/{name}/posts")
def channel_posts_resource(name: str) -> str:
    """Последние посты канала из кеша (без фетчинга с t.me)"""
    name = name.strip().lower().lstrip("@")
    channel = get_channel(name)

    if not channel:
        return f"Канал @{name} не найден"

    posts = get_posts([channel["id"]], "1970-01-01")[:10]

    if not posts:
        return f"Нет постов в кеше для @{name}"

    parts = [f"@{name}:"]

    for p in posts:
        preview = (p["text"][:200] + "…") if len(p["text"]) > 200 else p["text"]
        parts.append(f"[{p['date']}] {preview}")

    return "\n".join(parts)


@mcp.prompt()
def digest(days: int = 7, channels: str | None = None):
    """Составить дайджест постов за последние N дней по указанным каналам"""
    instruction = (
        f"посмотри в методе query_posts(days={days}) посты "
        f"и составь дайджест по указанным каналам. "
        f"по каждому каналу 2-3 предложения на главные темы. "
        f"Если каналов нет - сообщи об этом пользователю. "
        f"Если темы пересекаются - не нужно их отображать, покажи один раз, "
        f"а в остальных источниках пропусти данную тему."
    )

    if channels is None:
        return [
            base.UserMessage(
                EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri="tg://channels",
                        text=channels_resource(),
                        mimeType="text/plain",
                    ),
                )
            ),
            base.UserMessage(instruction),
        ]

    return [
        base.UserMessage(f"Каналы: {channels}\n\n{instruction}"),
    ]


@mcp.completion()
async def complete_channel_name(ref, argument: CompletionArgument, context) -> Completion | None:
    if isinstance(ref, ResourceTemplateReference):
        channels = list_channels()
        names = [c["channelname"] for c in channels]
        return Completion(
            values=[
                n for n in names
                if n.lower().startswith(argument.value.lower())
            ]
        )

    if isinstance(ref, PromptReference) and argument.name == "channels":
        channels = list_channels()
        names = [c["channelname"] for c in channels]
        return Completion(
            values=[
                n for n in names
                if n.lower().startswith(argument.value.lower())
            ]
        )

    return None


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
