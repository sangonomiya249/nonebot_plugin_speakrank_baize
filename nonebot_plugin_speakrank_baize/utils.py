"""发言排行插件 - 工具函数"""
import asyncio
import httpx
from pathlib import Path
from io import BytesIO
from typing import Optional
from PIL import Image, ImageDraw

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageSegment


async def send_image_safe(bot: Bot, group_id: int, img_path: Path,
                          wait_max: float = 3.0, wait_step: float = 0.15):
    """安全发送图片：等待文件写入完成，校验大小，二进制发送"""
    waited = 0.0
    abs_path = img_path.resolve()
    while not abs_path.exists() and waited < wait_max:
        await asyncio.sleep(wait_step)
        waited += wait_step

    if not abs_path.exists():
        logger.error(f"图片文件缺失：{abs_path}")
        await bot.send_group_msg(group_id=group_id, message="图片生成失败，请重试！")
        return

    stat = abs_path.stat()
    if stat.st_size < 100:
        logger.error(f"图片损坏：{abs_path} size:{stat.st_size}")
        await bot.send_group_msg(group_id=group_id, message="图片生成异常，请重试！")
        return

    try:
        with open(abs_path, "rb") as f:
            img_bytes = f.read()
        seg = MessageSegment.image(img_bytes)
        await bot.send_group_msg(group_id=group_id, message=seg)
        logger.info(f"图片发送成功：{abs_path.name}")
    except Exception as e:
        logger.error(f"发送图片失败：{e}")


async def fetch_group_avatar(client: httpx.AsyncClient, group_id: int,
                             size: int = 100) -> Optional[Image.Image]:
    """获取群头像"""
    url = f"http://p.qlogo.cn/gh/{group_id}/{group_id}/{size}"
    try:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        return img.resize((50, 50))
    except Exception:
        return None


async def fetch_daily_quote(url: str, max_len: int = 34) -> str:
    """获取每日一言"""
    fallback = "感谢各位的活跃发言"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        quote = str(data.get("tangdouz", "")).strip() if isinstance(data, dict) else ""
        if not quote:
            return fallback
        if len(quote) > max_len:
            quote = quote[:max_len] + "..."
        return quote
    except Exception:
        return fallback


async def fetch_group_name_map(bot: Bot,
                               group_ids: list[int]) -> dict[int, str]:
    """批量获取群名称"""
    name_map: dict[int, str] = {}
    for gid in group_ids:
        try:
            info = await bot.call_api("get_group_info", group_id=gid, no_cache=False)
            if isinstance(info, dict):
                data = info.get("data") if isinstance(info.get("data"), dict) else info
                if isinstance(data, dict):
                    gname = str(data.get("group_name", "")).strip()
                    if gname:
                        name_map[gid] = gname
                        continue
        except Exception:
            pass
        name_map[gid] = ""
    return name_map


def create_gradient_bg(width: int, height: int,
                       top_color=(240, 245, 250),
                       bot_color=(255, 255, 255)) -> Image.Image:
    """创建渐变背景"""
    base = Image.new('RGB', (width, height), '#FFFFFF')
    draw = ImageDraw.Draw(base)
    for i in range(height):
        ratio = i / height
        r = int(top_color[0] + (bot_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bot_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bot_color[2] - top_color[2]) * ratio)
        draw.line([(0, i), (width, i)], fill=(r, g, b))
    return base
