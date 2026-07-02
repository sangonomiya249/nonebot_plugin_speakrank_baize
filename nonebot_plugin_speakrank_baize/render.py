"""发言排行插件 - 图片渲染"""
import base64
import json
import random
import httpx
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from nonebot import logger
from .config import Config
from .utils import fetch_daily_quote, fetch_group_avatar

# ── 随机贴纸 ──
_STICKERS = []
_STICKER_JSON = Path(__file__).parent / "screenshots.json"
if _STICKER_JSON.exists():
    try:
        _data = json.loads(_STICKER_JSON.read_text(encoding="utf-8"))
        for _b64 in _data.values():
            try:
                _img = Image.open(BytesIO(base64.b64decode(_b64))).convert("RGBA")
                if _img.width > 0 and _img.height > 0:
                    _STICKERS.append(_img)
            except Exception:
                pass
        if _STICKERS:
            logger.info(f"[发言排行] 已加载 {len(_STICKERS)} 张贴纸")
    except Exception as _e:
        logger.warning(f"[发言排行] 贴纸加载失败: {_e}")


def _paste_random_sticker(img: Image.Image, x: int, y: int, max_w: int = 130, max_h: int = 130):
    """在指定位置粘贴随机贴纸（带柔和底座，随机选择逻辑保持不变）"""
    if not _STICKERS:
        return
    sticker = random.choice(_STICKERS)
    sticker = sticker.copy()
    bbox = sticker.getbbox()
    if bbox:
        sticker = sticker.crop(bbox)

    ratio = min(max_w / sticker.width, max_h / sticker.height, 1.0)
    sw = max(1, int(sticker.width * ratio))
    sh = max(1, int(sticker.height * ratio))
    sticker_resized = sticker.resize((sw, sh), Image.LANCZOS)

    badge_w = max_w + 14
    badge_h = max_h + 12
    layer = Image.new("RGBA", (badge_w + 10, badge_h + 10), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)

    shadow_box = (6, 7, badge_w + 5, badge_h + 6)
    layer_draw.rounded_rectangle(shadow_box, radius=22, fill=(8, 98, 99, 42))
    card_box = (2, 2, badge_w + 1, badge_h + 1)
    layer_draw.rounded_rectangle(
        card_box,
        radius=22,
        fill=(229, 255, 249, 100),
        outline=(238, 255, 250, 190),
        width=2,
    )
    layer_draw.ellipse((10, 8, badge_w - 6, badge_h + 2), fill=(255, 255, 255, 34))
    layer_draw.arc((8, 6, badge_w - 1, badge_h - 1), 205, 330, fill=(18, 151, 147, 94), width=2)
    for cx, cy, r in (
        (badge_w - 22, 20, 4),
        (badge_w - 40, badge_h - 22, 3),
        (24, badge_h - 28, 3),
    ):
        layer_draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 190))

    sx = 2 + (badge_w - sw) // 2
    sy = 2 + (badge_h - sh) // 2 + 1
    layer.alpha_composite(sticker_resized, (sx, sy))
    img.paste(layer, (x - 4, y - 4), layer)


def _load_fonts(config: Config):
    """加载字体，失败则回退默认"""
    font_path = config.resolve_font_path()
    if font_path:
        try:
            return {
                "title": ImageFont.truetype(font_path, 36),
                "sub": ImageFont.truetype(font_path, 21),
                "header": ImageFont.truetype(font_path, 26),
                "name": ImageFont.truetype(font_path, 24),
                "id": ImageFont.truetype(font_path, 17),
                "count": ImageFont.truetype(font_path, 20),
                "stat": ImageFont.truetype(font_path, 32),
                "axis": ImageFont.truetype(font_path, 20),
                "value": ImageFont.truetype(font_path, 18),
                "date_label": ImageFont.truetype(font_path, 13),
            }
        except Exception as e:
            logger.error(f"字体加载失败: {e}")
    d = ImageFont.load_default()
    return {k: d for k in ["title","sub","header","name","id","count","stat",
                            "axis","value","date_label"]}


def _mix(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _draw_mint_background(img: Image.Image, draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """流萤印象背景：薄荷青绿渐变、星轨线和光点。"""
    top = (236, 255, 249)
    mid = (205, 249, 239)
    bottom = (179, 236, 239)
    for y in range(height):
        t = y / max(1, height - 1)
        color = _mix(top, mid, t / 0.58) if t < 0.58 else _mix(mid, bottom, (t - 0.58) / 0.42)
        draw.line([(0, y), (width, y)], fill=color)

    # grid / star-rail traces
    for x in range(-height, width, 58):
        draw.line([(x, 0), (x + height, height)], fill=(154, 220, 211), width=1)
    for x in range(0, width, 92):
        draw.line([(x, 0), (x, height)], fill=(213, 248, 241), width=1)
    for y in range(0, height, 88):
        draw.line([(0, y), (width, y)], fill=(213, 248, 241), width=1)

    # Firefly soft glow spots
    for box, fill in (
        ((-160, -120, 360, 300), (178, 255, 225)),
        ((width - 270, -110, width + 170, 260), (143, 230, 206)),
        ((width - 250, height - 310, width + 170, height + 110), (180, 243, 255)),
    ):
        draw.ellipse(box, fill=fill)
    for cx, cy, r in (
        (width - 118, 94, 7),
        (width - 72, 150, 4),
        (92, 82, 5),
        (width - 180, height - 92, 5),
        (148, height - 118, 4),
    ):
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255))


def _paste_gradient_roundrect(
    img: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
    width: int = 1,
) -> None:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    patch = Image.new("RGB", (w, h), left)
    patch_draw = ImageDraw.Draw(patch)
    for x in range(w):
        color = _mix(left, right, x / max(1, w - 1))
        patch_draw.line([(x, 0), (x, h)], fill=color)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
    img.paste(patch, (x1, y1), mask)
    if outline:
        ImageDraw.Draw(img).rounded_rectangle(box, radius=radius, outline=outline, width=width)


def _draw_firefly_header(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    subtitle: str,
    fonts: dict,
) -> None:
    x1, y1, x2, y2 = box
    _paste_gradient_roundrect(
        img, box, 26,
        (16, 183, 163),
        (119, 226, 208),
        outline=(232, 255, 248),
        width=3,
    )
    draw.rounded_rectangle((x1 + 10, y1 + 10, x2 - 10, y2 - 10), radius=20,
                           outline=(22, 128, 126), width=2)
    draw.ellipse((x2 - 220, y1 - 68, x2 - 16, y1 + 116), fill=(181, 255, 236))
    draw.ellipse((x2 - 106, y1 + 42, x2 - 88, y1 + 60), fill=(255, 255, 255))
    draw.ellipse((x2 - 146, y1 + 88, x2 - 136, y1 + 98), fill=(246, 255, 250))
    draw.line((x1 + 28, y1 + 22, x2 - 40, y1 + 22), fill=(232, 255, 249), width=2)
    draw.line((x1 + 34, y2 - 14, x2 - 240, y2 - 14), fill=(12, 124, 120), width=2)
    box_h = y2 - y1
    title_y = y1 + max(20, int(box_h * 0.18))
    subtitle_y = y1 + max(70, int(box_h * 0.58))
    title_x = x1 + 142  # 左侧留空给贴纸
    draw.text((title_x, title_y), title, font=fonts["title"], fill=(245, 255, 251))
    draw.text((title_x, subtitle_y), subtitle, font=fonts["sub"], fill=(220, 255, 248))


def _draw_bar_gradient(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    left: tuple[int, int, int],
    right: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = box
    for x in range(x1, x2):
        color = _mix(left, right, (x - x1) / max(1, x2 - x1 - 1))
        draw.line([(x, y1), (x, y2)], fill=color)
    draw.rounded_rectangle(box, radius=radius, outline=(234, 255, 249), width=1)


async def generate_stats_image(
    data: list,
    group_id: int,
    config: Config,
    title_suffix: str = "",
    active_people: int | None = None,
    group_name_map: dict[int, str] | None = None,
    period_text: str = "",
    total_count_override: int | None = None,
) -> bytes:
    """生成排行统计图片（返回 PNG bytes，不写磁盘）"""
    W, H = config.rank_image_width, config.rank_image_height
    TOP_H, ROW_H, LIST_TOP = 170, 88, 250
    L, R = 34, W - 34
    BAR_X, BAR_W, BAR_H = 620, 300, 22

    img = Image.new("RGB", (W, H), "#eafff9")
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts(config)

    _draw_mint_background(img, draw, W, H)
    draw.text((W - 250, H - 144), "FIREFLY", font=fonts["title"], fill=(156, 224, 215))

    title_date = datetime.now(config.tz).strftime("%Y-%m-%d")
    is_group_rank = len(data) > 0 and len(data[0]) == 2
    total_count = (
        int(total_count_override) if total_count_override is not None
        else int(sum((x[1] if is_group_rank else x[2]) for x in data)) if data else 0
    )
    if active_people is None:
        active_people = len(data) if not is_group_rank else 0
    if "群发言排行" in title_suffix:
        title_text = f"所有群活跃排行榜 {title_suffix}"
        total_label = "所有群总发言数"
        people_label = "所有群活跃人数"
    else:
        title_text = f"群 {group_id} 活跃排行榜 {title_suffix}"
        total_label = "信息总数"
        people_label = "活跃人数"
    subtitle = f"统计区间：{period_text}" if period_text else f"统计日期：{title_date}"
    _draw_firefly_header(img, draw, (L, 24, R, TOP_H), title_text, subtitle, fonts)

    # 右上统计徽标
    sx1, sy1, sx2, sy2 = R - 300, 42, R - 24, 152
    draw.rounded_rectangle((sx1, sy1, sx2, sy2), radius=18,
                           fill=(223, 255, 248), outline=(92, 202, 184), width=2)
    draw.text((sx1 + 14, sy1 + 8), f"{total_label}：{total_count}",
              font=fonts["sub"], fill=(11, 98, 99))
    draw.text((sx1 + 14, sy1 + 48), f"{people_label}：{active_people}",
              font=fonts["sub"], fill=(20, 134, 132))

    # 表头
    draw.rounded_rectangle((L, 194, R, 240), radius=16,
                           fill=(225, 255, 248), outline=(121, 219, 201), width=2)
    draw.text((126, 204), ("群信息" if is_group_rank else "用户信息"),
              font=fonts["header"], fill=(10, 91, 94))
    draw.text((BAR_X, 204), "发言统计", font=fonts["header"], fill=(10, 91, 94))

    # 排序数据
    data_sorted = sorted(data, key=lambda x: x[1] if is_group_rank else x[2], reverse=True)
    max_rows = max(1, (H - LIST_TOP - 92) // ROW_H)
    top_n = min(config.max_display_rank, max_rows)
    display_data = data_sorted[:top_n]
    max_count = max([x[1] if is_group_rank else x[2] for x in display_data]) if display_data else 1

    badge_colors = {
        1: ((255, 224, 103), (255, 248, 198)),
        2: ((160, 232, 221), (229, 255, 249)),
        3: ((132, 213, 255), (224, 249, 255)),
    }
    bar_palettes = [
        ((20, 186, 164), (139, 230, 206)),
        ((58, 201, 214), (176, 244, 255)),
        ((85, 210, 170), (205, 255, 225)),
        ((92, 190, 232), (134, 233, 214)),
    ]

    async with httpx.AsyncClient(timeout=10) as client:
        for idx, item in enumerate(display_data, start=1):
            y = LIST_TOP + (idx - 1) * ROW_H
            card_fill = (246, 255, 252) if idx % 2 else (236, 255, 249)
            draw.rounded_rectangle((L, y, R, y + ROW_H - 8), radius=18,
                                   fill=card_fill, outline=(149, 224, 211), width=2)
            draw.line((L + 22, y + 12, R - 22, y + 12), fill=(229, 255, 248), width=1)

            # 排名徽章
            by = y + 26
            c1, c2 = badge_colors.get(idx, ((161, 222, 212), (230, 255, 249)))
            draw.ellipse((50, by, 86, by + 36), fill=c1, outline=c2, width=2)
            rank_text = str(idx)
            rb = draw.textbbox((0, 0), rank_text, font=fonts["sub"])
            draw.text((68 - (rb[2] - rb[0]) // 2, by + 6), rank_text,
                      font=fonts["sub"], fill=(9, 88, 89))

            # 头像
            if not is_group_rank:
                user_id, nickname, count_val = item
                try:
                    avatar_url = f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
                    res = await client.get(avatar_url)
                    av = Image.open(BytesIO(res.content)).convert("RGBA").resize((54, 54))
                    mask = Image.new("L", (54, 54), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, 54, 54), fill=255)
                    img.paste(av, (106, y + 16), mask=mask)
                except Exception:
                    draw.ellipse((106, y + 16, 160, y + 70), fill=(121, 219, 201))
                id_text = f"QQ: {user_id}"
            else:
                group_id_, count_val = item
                avatar_img = await fetch_group_avatar(client, group_id_)
                if avatar_img:
                    mask = Image.new("L", (54, 54), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, 54, 54), fill=255)
                    img.paste(avatar_img.resize((54, 54)), (106, y + 16), mask=mask)
                else:
                    draw.ellipse((106, y + 16, 160, y + 70), fill=(121, 219, 201))
                nickname = group_name_map.get(group_id_, f"群 {group_id_}") if group_name_map else f"群 {group_id_}"
                id_text = f"ID: {group_id_}"

            nickname_disp = nickname[:13] + "..." if len(nickname) > 13 else nickname
            draw.text((178, y + 18), nickname_disp, font=fonts["name"], fill=(18, 70, 73))
            draw.text((178, y + 50), id_text, font=fonts["id"], fill=(62, 139, 139))

            # 进度条
            bar_y = y + 35
            draw.rounded_rectangle((BAR_X, bar_y, BAR_X + BAR_W, bar_y + BAR_H),
                                   radius=11, fill=(206, 244, 237))
            bar_len = int(BAR_W * (count_val / max_count if max_count else 1))
            if bar_len > 0:
                c_start, c_end = bar_palettes[(idx - 1) % len(bar_palettes)]
                _draw_bar_gradient(
                    draw,
                    (BAR_X, bar_y, BAR_X + min(bar_len, BAR_W), bar_y + BAR_H),
                    11,
                    c_start,
                    c_end,
                )

            # 次数胶囊
            count_text = str(count_val)
            cb = draw.textbbox((0, 0), count_text, font=fonts["count"])
            cw = cb[2] - cb[0]
            px1, px2 = BAR_X + BAR_W + 16, BAR_X + BAR_W + 16 + max(54, cw + 24)
            draw.rounded_rectangle((px1, y + 30, px2, y + 62), radius=14,
                                   fill=(222, 255, 248), outline=(82, 199, 181), width=1)
            draw.text((px1 + (px2 - px1 - cw) // 2, y + 35), count_text,
                      font=fonts["count"], fill=(9, 107, 104))

    # 底部
    draw.rounded_rectangle((L, H - 64, R, H - 24), radius=14,
                           fill=(225, 255, 248), outline=(137, 219, 204), width=1)
    daily_quote = await fetch_daily_quote(config.daily_quote_url, config.daily_quote_max_length)
    draw.text((50, H - 55), daily_quote, font=fonts["sub"], fill=(17, 111, 112))
    if len(data) > top_n:
        draw.text((R - 270, H - 55), f"仅显示前{top_n}位，共{len(data)}位",
                  font=fonts["sub"], fill=(62, 139, 139))

    # 贴纸（最顶层，左上角标题区域）
    _paste_random_sticker(img, L + 20, 54, max_w=76, max_h=76)

    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def generate_activity_line_chart(
    daily_data: list[tuple[str, int, int]],
    group_id: int, day_count: int, config: Config
) -> bytes:
    """生成每日发言折线图（返回 PNG bytes，不写磁盘）"""
    vertical_mode = day_count > 30
    if not vertical_mode:
        width, height = 1280, 840
        ml, mr, mt, mb = 90, 50, 190, 210
    else:
        width = 1280
        row_gap = 20 if day_count <= 60 else (16 if day_count <= 120 else (12 if day_count <= 240 else 10))
        height = max(1040, 250 + day_count * row_gap + 190)
        ml, mr, mt, mb = 250, 80, 190, 190

    pw, ph = width - ml - mr, height - mt - mb
    img = Image.new("RGB", (width, height), "#eafff9")
    draw = ImageDraw.Draw(img)

    _draw_mint_background(img, draw, width, height)

    font_path = config.resolve_font_path()
    def _tf(sz):
        try:
            return ImageFont.truetype(font_path, sz) if font_path else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()

    title_font = _tf(36)
    sub_font = _tf(24)
    axis_font = _tf(20 if not vertical_mode else (16 if day_count <= 120 else 13))
    value_font = _tf(18 if not vertical_mode else (14 if day_count <= 120 else 12))
    dl_size = 18 if day_count <= 7 else (15 if day_count <= 14 else (13 if day_count <= 21 else 12))
    al_size = 15 if day_count <= 7 else (13 if day_count <= 14 else (11 if day_count <= 21 else 10))
    date_label_font = _tf(dl_size)
    active_label_font = _tf(al_size)
    draw.text((width - 270, 160), "FIREFLY", font=title_font, fill=(156, 224, 215))

    sd = daily_data[0][0] if daily_data else "-"
    ed = daily_data[-1][0] if daily_data else datetime.now(config.tz).strftime("%Y-%m-%d")
    _draw_firefly_header(
        img,
        draw,
        (50, 22, width - 50, 154),
        f"群 {group_id} 近{day_count}天活跃趋势",
        f"统计维度：每日发言次数  |  起始：{sd}  截止：{ed}",
        {"title": title_font, "sub": sub_font},
    )

    x1, y1 = ml, mt
    x2, y2 = ml + pw, mt + ph
    draw.rounded_rectangle((x1 - 18, y1 - 18, x2 + 18, y2 + 18), radius=24,
                           fill=(246, 255, 252), outline=(122, 219, 201), width=2)

    counts = [msg_cnt for _, msg_cnt, _ in daily_data]
    max_count = max(counts) if counts else 1
    x_top = max(5, int(max_count * 1.15))
    n = len(daily_data)

    if not vertical_mode:
        for i in range(6):
            gy = y1 + int(ph * i / 5)
            val = int(x_top * (5 - i) / 5)
            draw.line([(x1, gy), (x2, gy)], fill=(195, 237, 229), width=1)
            draw.text((20, gy - 10), str(val), fill=(62, 139, 139), font=axis_font)
        draw.line([(x1, y1), (x1, y2)], fill=(92, 202, 184), width=2)
        draw.line([(x1, y2), (x2, y2)], fill=(92, 202, 184), width=2)
        step_x = pw if n <= 1 else pw / (n - 1)
        points = []
        for i, (day_s, cnt, active_cnt) in enumerate(daily_data):
            px = int(x1 + step_x * i)
            py = int(y2 - (cnt / x_top) * ph) if x_top > 0 else y2
            points.append((px, py))
            dbox = draw.textbbox((0, 0), day_s[5:], font=date_label_font)
            abox = draw.textbbox((0, 0), f"活跃{active_cnt}", font=active_label_font)
            draw.text((px - (dbox[2] - dbox[0]) // 2, y2 + 18),
                      day_s[5:], fill=(47, 126, 128), font=date_label_font)
            draw.text((px - (abox[2] - abox[0]) // 2, y2 + 38),
                      f"活跃{active_cnt}", fill=(20, 166, 151), font=active_label_font)
        if points:
            draw.polygon([(points[0][0], y2)] + points + [(points[-1][0], y2)],
                         fill=(205, 255, 244))
            draw.line(points, fill=(20, 186, 164), width=5)
            for px, py in points:
                draw.ellipse((px - 6, py - 6, px + 6, py + 6),
                             fill=(255, 255, 255), outline=(20, 186, 164), width=2)
            for i, (px, py) in enumerate(points):
                draw.text((px - 10, py - 30), str(daily_data[i][1]),
                          fill=(9, 107, 104), font=value_font)
    else:
        for i in range(7):
            gx = x1 + int(pw * i / 6)
            val = int(x_top * i / 6)
            draw.line([(gx, y1), (gx, y2)], fill=(195, 237, 229), width=1)
            vb = draw.textbbox((0, 0), str(val), font=axis_font)
            draw.text((gx - (vb[2] - vb[0]) // 2, y2 + 12), str(val),
                      fill=(62, 139, 139), font=axis_font)
        draw.line([(x1, y1), (x1, y2)], fill=(92, 202, 184), width=2)
        draw.line([(x1, y2), (x2, y2)], fill=(92, 202, 184), width=2)
        step_y = ph if n <= 1 else ph / (n - 1)
        points = []
        for i, (day_s, cnt, active_cnt) in enumerate(daily_data):
            py = int(y1 + step_y * i)
            px = int(x1 + (cnt / x_top) * pw) if x_top > 0 else x1
            points.append((px, py))
            draw.text((38, py - 10), day_s[5:], fill=(47, 126, 128), font=axis_font)
            draw.text((110, py - 10), f"活跃{active_cnt}", fill=(20, 166, 151), font=axis_font)
            draw.line([(x1, py), (x2, py)], fill=(203, 240, 233), width=1)
        if points:
            draw.line(points, fill=(20, 186, 164), width=4)
            for idx, (px, py) in enumerate(points):
                draw.ellipse((px - 4, py - 4, px + 4, py + 4),
                             fill=(255, 255, 255), outline=(20, 186, 164), width=2)
                draw.text((px + 8, py - 10), str(daily_data[idx][1]),
                          fill=(9, 107, 104), font=value_font)

    total = sum(counts)
    avg = total / n if n else 0
    peak = max_count
    peak_day = daily_data[counts.index(peak)][0] if daily_data else "-"
    actives = [a for _, _, a in daily_data]
    total_a = sum(actives)
    avg_a = total_a / n if n else 0
    peak_a = max(actives) if actives else 0
    peak_ad = daily_data[actives.index(peak_a)][0] if daily_data else "-"
    summary = (
        f"总发言: {total}   日均发言: {avg:.1f}   峰值发言: {peak} ({peak_day})\n"
        f"活跃人数(日): 总计{total_a}   日均{avg_a:.1f}   峰值{peak_a} ({peak_ad})"
    )
    draw.rounded_rectangle((50, height - 112, width - 50, height - 30), radius=22,
                           fill=(225, 255, 248), outline=(137, 219, 204), width=2)
    draw.text((74, height - 96), summary, fill=(17, 111, 112), font=sub_font)

    # 贴纸（最顶层）
    _paste_random_sticker(img, 70, 50, max_w=76, max_h=76)

    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
