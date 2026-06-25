"""发言排行插件 - 群聊活跃统计与排行"""
from datetime import datetime, timedelta
from typing import Any

from nonebot import get_driver, logger, get_bot, on_command, on_message, on
from nonebot.plugin import require
from nonebot.adapters.onebot.v11 import (
    Bot, Event, GroupMessageEvent, MessageEvent, Message, MessageSegment
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.typing import T_State

try:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler
except Exception as e:
    logger.warning(f"nonebot_plugin_apscheduler 加载失败，将禁用定时任务: {e}")
    class _DummyScheduler:
        def scheduled_job(self, *args, **kwargs):
            def _deco(func):
                return func
            return _deco
    scheduler = _DummyScheduler()

from .config import Config
from .database import (
    init_db, insert_message, get_distinct_groups,
    query_group_rank, query_historical_rank,
    query_total_group_rank, query_historical_group_rank,
    query_group_period_stats, query_group_daily_counts,
    count_historical_active, count_recent_active,
)
from .render import generate_stats_image, generate_activity_line_chart
from .utils import send_image_safe, fetch_group_name_map

# ── 插件配置 ──
plugin_config = Config()

__plugin_meta__ = PluginMetadata(
    name="群聊活跃统计",
    description="每日定时自动统计群聊发言排行榜，支持手动触发多种排行",
    usage=(
        "自动触发或使用命令,生成聊天次数排行榜\n"
        "发送「/今日发言排行」     获取本群今日内的排行\n\n"
        "发送「/发言排行 <天数>」  获取本群任意天数的排行\n\n"
        "发送「/活跃统计 <天数>」  获取本群近N天每日发言折线图\n\n"
        "发送「/群发言排行 <天数>」获取所有群近N天的排行\n\n"
        "发送「/历史发言排行」     获取本群历史总排行\n\n"
        "发送「/群历史发言排行」   获取所有群历史总排行"
    ),
    config=Config,
)

# ── 数据目录 ──
plugin_config.data_path.mkdir(parents=True, exist_ok=True)


@get_driver().on_startup
async def _():
    await init_db(plugin_config.db_path)


# ═══════════════════════ 消息记录 ═══════════════════════

msg_handler = on_message(priority=99, block=False)


@msg_handler.handle()
async def record_message(event: GroupMessageEvent):
    await insert_message(
        plugin_config.db_path,
        event.group_id,
        event.user_id,
        event.sender.card or event.sender.nickname,
        datetime.fromtimestamp(event.time).strftime("%Y-%m-%d %H:%M:%S"),
    )


bot_msg_sent_handler = on(type="message_sent", priority=15, block=False)


@bot_msg_sent_handler.handle()
async def record_bot_sent_message(event: Event, state: T_State):
    """记录机器人自己发送的消息"""
    try:
        d = event.dict()
        if d.get("message_type") != "group":
            return
        gid = d.get("group_id")
        uid = d.get("user_id")
        if not gid or not uid:
            return
        sender = d.get("sender", {})
        nickname = sender.get("card") or sender.get("nickname") or f"Bot_{uid}"
        ts = d.get("time", int(datetime.now().timestamp()))
        await insert_message(
            plugin_config.db_path, gid, uid, nickname,
            datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
        )
    except Exception as e:
        logger.error(f"记录机器人消息失败: {e}")


# ═══════════════════════ 定时任务 ═══════════════════════

@scheduler.scheduled_job(
    "cron",
    hour=plugin_config.daily_rank_hour,
    minute=plugin_config.daily_rank_minute,
    misfire_grace_time=450,
    timezone="Asia/Shanghai"
)
async def daily_statistics():
    """每日定时发送今日排行"""
    now = datetime.now(plugin_config.tz)
    start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
    group_ids = await get_distinct_groups(plugin_config.db_path)
    bot = get_bot()
    for gid in group_ids:
        try:
            stats = await query_group_rank(plugin_config.db_path, gid, start_time, now)
            if not stats:
                continue
            total_msgs, active_users = await query_group_period_stats(
                plugin_config.db_path, gid, start_time, now)
            img_path = await generate_stats_image(
                stats, gid, plugin_config, "今日",
                active_people=active_users, total_count_override=total_msgs,
                period_text=f"{start_time.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}")
            await send_image_safe(bot, gid, img_path,
                                  plugin_config.image_wait_max,
                                  plugin_config.image_wait_step)
        except Exception as e:
            logger.error(f"群{gid}统计失败: {e}")


@scheduler.scheduled_job(
    "cron", day_of_week="sun",
    hour=plugin_config.weekly_chart_hour,
    minute=plugin_config.weekly_chart_minute,
    misfire_grace_time=450, timezone="Asia/Shanghai"
)
async def weekly_statistics():
    """每周日定时发送近7天活跃折线图"""
    group_ids = await get_distinct_groups(plugin_config.db_path)
    bot = get_bot()
    for gid in group_ids:
        try:
            daily_data = await query_group_daily_counts(
                plugin_config.db_path, gid, 7, plugin_config.tz)
            if not daily_data:
                continue
            img_path = generate_activity_line_chart(daily_data, gid, 7, plugin_config)
            await send_image_safe(bot, gid, img_path,
                                  plugin_config.image_wait_max,
                                  plugin_config.image_wait_step)
        except Exception as e:
            logger.error(f"定时发送群{gid}近7天活跃图失败: {e}")


# ═══════════════════════ 命令处理器 ═══════════════════════

today_rank_cmd = on_command("今日发言排行", priority=10, block=True)


@today_rank_cmd.handle()
async def handle_today_rank(event: MessageEvent):
    gid = event.group_id if hasattr(event, 'group_id') else None
    if not gid:
        await today_rank_cmd.finish("请在群里使用此命令。")
    now = datetime.now(plugin_config.tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    data = await query_group_rank(plugin_config.db_path, gid, start, now)
    if not data:
        await today_rank_cmd.finish("暂无今日发言数据。")
    total_msgs, active_users = await query_group_period_stats(
        plugin_config.db_path, gid, start, now)
    img_path = await generate_stats_image(
        data, gid, plugin_config, "今日",
        active_people=active_users, total_count_override=total_msgs,
        period_text=f"{start.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}")
    await send_image_safe(get_bot(), gid, img_path,
                          plugin_config.image_wait_max, plugin_config.image_wait_step)


week_rank_cmd = on_command("周发言排行", priority=10, block=True)


@week_rank_cmd.handle()
async def handle_week_rank(event: MessageEvent):
    gid = event.group_id if hasattr(event, 'group_id') else None
    if not gid:
        await week_rank_cmd.finish("请在群里使用此命令。")
    now = datetime.now(plugin_config.tz)
    start = now - timedelta(days=7)
    data = await query_group_rank(plugin_config.db_path, gid, start, now)
    if not data:
        await week_rank_cmd.finish("暂无近7天发言数据。")
    img_path = await generate_stats_image(data, gid, plugin_config, "近7天")
    await send_image_safe(get_bot(), gid, img_path,
                          plugin_config.image_wait_max, plugin_config.image_wait_step)


month_rank_cmd = on_command("月发言排行", priority=10, block=True)


@month_rank_cmd.handle()
async def handle_month_rank(event: MessageEvent):
    gid = event.group_id if hasattr(event, 'group_id') else None
    if not gid:
        await month_rank_cmd.finish("请在群里使用此命令。")
    now = datetime.now(plugin_config.tz)
    start = now - timedelta(days=30)
    data = await query_group_rank(plugin_config.db_path, gid, start, now)
    if not data:
        await month_rank_cmd.finish("暂无近30天发言数据。")
    img_path = await generate_stats_image(data, gid, plugin_config, "近30天")
    await send_image_safe(get_bot(), gid, img_path,
                          plugin_config.image_wait_max, plugin_config.image_wait_step)


custom_days_rank_cmd = on_command("发言排行", priority=10, block=True)


@custom_days_rank_cmd.handle()
async def handle_custom_days_rank(event: MessageEvent, args: Message = CommandArg()):
    gid = event.group_id if hasattr(event, 'group_id') else None
    if not gid:
        await custom_days_rank_cmd.finish("请在群里使用此命令。")
    days_text = args.extract_plain_text().strip()
    if not days_text:
        await custom_days_rank_cmd.finish("请指定天数，用法：/发言排行 10")
    try:
        days = int(days_text)
        if not 1 <= days <= plugin_config.max_query_days:
            await custom_days_rank_cmd.finish(
                f"天数范围为 1-{plugin_config.max_query_days} 天。")
    except ValueError:
        await custom_days_rank_cmd.finish("请输入有效数字。")
    now = datetime.now(plugin_config.tz)
    start = now - timedelta(days=days)
    data = await query_group_rank(plugin_config.db_path, gid, start, now)
    if not data:
        await custom_days_rank_cmd.finish(f"暂无近{days}天的发言数据。")
    period_text = f"{start.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}"
    img_path = await generate_stats_image(
        data, gid, plugin_config, f"近{days}天", period_text=period_text)
    await send_image_safe(get_bot(), gid, img_path,
                          plugin_config.image_wait_max, plugin_config.image_wait_step)


total_rank_cmd = on_command("群发言排行", priority=10, block=True)


@total_rank_cmd.handle()
async def handle_total_rank(event: MessageEvent, args: Message = CommandArg()):
    days_text = args.extract_plain_text().strip()
    days = 30
    if days_text:
        try:
            days = int(days_text)
            if not 1 <= days <= plugin_config.max_query_days:
                await total_rank_cmd.finish(
                    f"天数范围为 1-{plugin_config.max_query_days} 天。")
        except ValueError:
            await total_rank_cmd.finish("请输入有效数字。")
    data = await query_total_group_rank(plugin_config.db_path, days)
    if not data:
        await total_rank_cmd.finish(f"暂无近{days}天的群发言统计数据。")
    active_people = await count_recent_active(plugin_config.db_path, days)
    group_ids = [row[0] for row in data]
    bot = get_bot()
    group_name_map = await fetch_group_name_map(bot, group_ids)
    now = datetime.now(plugin_config.tz)
    img_path = await generate_stats_image(
        data, 0, plugin_config, f"近{days}天 群发言排行",
        active_people=active_people, group_name_map=group_name_map,
        period_text=f"{(now - timedelta(days=days)).strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}")
    gid = event.group_id if hasattr(event, 'group_id') else None
    if gid:
        await send_image_safe(bot, gid, img_path,
                              plugin_config.image_wait_max, plugin_config.image_wait_step)
    else:
        await total_rank_cmd.finish("请在群里使用此命令。")


historical_rank_cmd = on_command("历史发言排行", priority=10, block=True)


@historical_rank_cmd.handle()
async def handle_historical_rank(event: MessageEvent):
    gid = event.group_id if hasattr(event, 'group_id') else None
    if not gid:
        await historical_rank_cmd.finish("请在群里使用此命令。")
    data = await query_historical_rank(plugin_config.db_path, gid)
    if not data:
        await historical_rank_cmd.finish("暂无历史发言数据。")
    active_people = await count_historical_active(plugin_config.db_path, gid)
    img_path = await generate_stats_image(
        data, gid, plugin_config, "历史", active_people=active_people)
    await send_image_safe(get_bot(), gid, img_path,
                          plugin_config.image_wait_max, plugin_config.image_wait_step)


historical_group_rank_cmd = on_command("群历史发言排行", priority=10, block=True)


@historical_group_rank_cmd.handle()
async def handle_historical_group_rank(event: MessageEvent):
    data = await query_historical_group_rank(plugin_config.db_path)
    if not data:
        await historical_group_rank_cmd.finish("暂无群历史发言统计数据。")
    bot = get_bot()
    group_ids = [row[0] for row in data]
    group_name_map = await fetch_group_name_map(bot, group_ids)
    active_people = await count_historical_active(plugin_config.db_path)
    img_path = await generate_stats_image(
        data, 0, plugin_config, "历史 群发言排行",
        group_name_map=group_name_map, active_people=active_people)
    gid = event.group_id if hasattr(event, 'group_id') else None
    if gid:
        await send_image_safe(bot, gid, img_path,
                              plugin_config.image_wait_max, plugin_config.image_wait_step)
    else:
        await historical_group_rank_cmd.finish("请在群里使用此命令。")


active_stat_cmd = on_command("活跃统计", priority=10, block=True)


@active_stat_cmd.handle()
async def handle_active_stat(event: MessageEvent, args: Message = CommandArg()):
    gid = event.group_id if hasattr(event, "group_id") else None
    if not gid:
        await active_stat_cmd.finish("请在群里使用此命令。")
    days_text = args.extract_plain_text().strip()
    days = 7
    if days_text:
        try:
            days = int(days_text)
        except ValueError:
            await active_stat_cmd.finish("请输入有效天数（2-360），例如：/活跃统计 10")
    if not 2 <= days <= 360:
        await active_stat_cmd.finish("活跃统计天数范围为 2-360 天。")
    daily_data = await query_group_daily_counts(
        plugin_config.db_path, gid, days, plugin_config.tz)
    if not daily_data:
        await active_stat_cmd.finish(f"暂无近{days}天发言数据。")
    img_path = generate_activity_line_chart(daily_data, gid, days, plugin_config)
    await send_image_safe(get_bot(), gid, img_path,
                          plugin_config.image_wait_max, plugin_config.image_wait_step)
