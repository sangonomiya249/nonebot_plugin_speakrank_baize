"""发言排行插件 - 图片渲染"""
import httpx
from pathlib import Path
from io import BytesIO
from datetime import datetime
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from nonebot import logger
from .config import Config
from .utils import fetch_daily_quote, fetch_group_avatar


def _load_fonts(config: Config):
    """加载字体，失败则回退默认"""
    font_path = config.resolve_font_path()
    if font_path:
        try:
            return {
                "title": ImageFont.truetype(font_path, 40),
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


async def generate_stats_image(
    data: list,
    group_id: int,
    config: Config,
    title_suffix: str = "",
    active_people: int | None = None,
    group_name_map: dict[int, str] | None = None,
    period_text: str = "",
    total_count_override: int | None = None,
) -> Path:
    """生成排行统计图片"""
    W, H = config.rank_image_width, config.rank_image_height
    TOP_H, ROW_H, LIST_TOP = 170, 88, 250
    L, R = 34, W - 34
    BAR_X, BAR_W, BAR_H = 620, 300, 22

    img = Image.new("RGB", (W, H), "#111D35")
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts(config)

    # 深色渐变背景
    for y in range(H):
        t = y / max(1, H - 1)
        draw.line([(0, y), (W, y)],
                  fill=(int(15 + 16 * t), int(29 + 30 * t), int(52 + 50 * t)))
    for i in range(0, W, 38):
        draw.line([(i, 0), (i - 220, H)], fill=(24, 44, 77), width=1)

    # 顶部信息卡
    draw.rounded_rectangle((L, 24, R, TOP_H), radius=24,
                           fill=(29, 49, 82), outline=(102, 140, 196), width=2)
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
    draw.text((56, 48), title_text, font=fonts["title"], fill=(241, 247, 255))
    if period_text:
        draw.text((56, 102), f"统计区间：{period_text}", font=fonts["sub"], fill=(181, 209, 242))
    else:
        draw.text((56, 102), f"统计日期：{title_date}", font=fonts["sub"], fill=(181, 209, 242))

    # 右上统计徽标
    sx1, sy1, sx2, sy2 = R - 300, 42, R - 24, 152
    draw.rounded_rectangle((sx1, sy1, sx2, sy2), radius=18,
                           fill=(45, 75, 118), outline=(128, 173, 236), width=2)
    draw.text((sx1 + 14, sy1 + 8), f"{total_label}：{total_count}",
              font=fonts["sub"], fill=(191, 220, 252))
    draw.text((sx1 + 14, sy1 + 48), f"{people_label}：{active_people}",
              font=fonts["sub"], fill=(214, 231, 252))

    # 表头
    draw.rounded_rectangle((L, 194, R, 240), radius=16,
                           fill=(42, 67, 109), outline=(111, 152, 214), width=1)
    draw.text((126, 204), ("群信息" if is_group_rank else "用户信息"),
              font=fonts["header"], fill=(236, 245, 255))
    draw.text((BAR_X, 204), "发言统计", font=fonts["header"], fill=(236, 245, 255))

    # 排序数据
    data_sorted = sorted(data, key=lambda x: x[1] if is_group_rank else x[2], reverse=True)
    max_rows = max(1, (H - LIST_TOP - 92) // ROW_H)
    top_n = min(config.max_display_rank, max_rows)
    display_data = data_sorted[:top_n]
    max_count = max([x[1] if is_group_rank else x[2] for x in display_data]) if display_data else 1

    badge_colors = {
        1: ((255, 205, 74), (255, 231, 157)),
        2: ((173, 190, 216), (220, 231, 248)),
        3: ((224, 145, 103), (244, 199, 160)),
    }
    bar_palettes = [
        ((87, 181, 255), (72, 240, 205)),
        ((124, 149, 255), (96, 219, 255)),
        ((160, 143, 255), (120, 202, 255)),
        ((103, 175, 255), (74, 140, 255)),
    ]

    async with httpx.AsyncClient(timeout=10) as client:
        for idx, item in enumerate(display_data, start=1):
            y = LIST_TOP + (idx - 1) * ROW_H
            card_fill = (25, 41, 70) if idx % 2 else (29, 47, 79)
            draw.rounded_rectangle((L, y, R, y + ROW_H - 8), radius=18,
                                   fill=card_fill, outline=(73, 106, 153), width=1)

            # 排名徽章
            by = y + 26
            c1, c2 = badge_colors.get(idx, ((95, 122, 161), (130, 156, 193)))
            draw.ellipse((50, by, 86, by + 36), fill=c1, outline=c2, width=2)
            rank_text = str(idx)
            rb = draw.textbbox((0, 0), rank_text, font=fonts["sub"])
            draw.text((68 - (rb[2] - rb[0]) // 2, by + 6), rank_text,
                      font=fonts["sub"], fill=(20, 34, 56))

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
                    draw.ellipse((106, y + 16, 160, y + 70), fill=(88, 116, 156))
                id_text = f"QQ: {user_id}"
            else:
                group_id_, count_val = item
                avatar_img = await fetch_group_avatar(client, group_id_)
                if avatar_img:
                    mask = Image.new("L", (54, 54), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, 54, 54), fill=255)
                    img.paste(avatar_img.resize((54, 54)), (106, y + 16), mask=mask)
                else:
                    draw.ellipse((106, y + 16, 160, y + 70), fill=(88, 116, 156))
                nickname = group_name_map.get(group_id_, f"群 {group_id_}") if group_name_map else f"群 {group_id_}"
                id_text = f"ID: {group_id_}"

            nickname_disp = nickname[:13] + "..." if len(nickname) > 13 else nickname
            draw.text((178, y + 18), nickname_disp, font=fonts["name"], fill=(237, 245, 255))
            draw.text((178, y + 50), id_text, font=fonts["id"], fill=(156, 186, 224))

            # 进度条
            bar_y = y + 35
            draw.rounded_rectangle((BAR_X, bar_y, BAR_X + BAR_W, bar_y + BAR_H),
                                   radius=11, fill=(44, 63, 95))
            bar_len = int(BAR_W * (count_val / max_count if max_count else 1))
            if bar_len > 0:
                c_start, c_end = bar_palettes[(idx - 1) % len(bar_palettes)]
                for j in range(bar_len):
                    t = j / max(1, bar_len - 1)
                    r = int(c_start[0] + (c_end[0] - c_start[0]) * t)
                    g = int(c_start[1] + (c_end[1] - c_start[1]) * t)
                    b = int(c_start[2] + (c_end[2] - c_start[2]) * t)
                    draw.line([(BAR_X + j, bar_y), (BAR_X + j, bar_y + BAR_H)], fill=(r, g, b))
                draw.rounded_rectangle((BAR_X, bar_y, BAR_X + min(bar_len, BAR_W), bar_y + BAR_H),
                                       radius=11, outline=(213, 237, 255), width=1)

            # 次数胶囊
            count_text = str(count_val)
            cb = draw.textbbox((0, 0), count_text, font=fonts["count"])
            cw = cb[2] - cb[0]
            px1, px2 = BAR_X + BAR_W + 16, BAR_X + BAR_W + 16 + max(54, cw + 24)
            draw.rounded_rectangle((px1, y + 30, px2, y + 62), radius=14,
                                   fill=(69, 103, 153), outline=(125, 167, 225), width=1)
            draw.text((px1 + (px2 - px1 - cw) // 2, y + 35), count_text,
                      font=fonts["count"], fill=(238, 247, 255))

    # 底部
    draw.rounded_rectangle((L, H - 64, R, H - 24), radius=14, fill=(29, 49, 82))
    daily_quote = await fetch_daily_quote(config.daily_quote_url, config.daily_quote_max_length)
    draw.text((50, H - 55), daily_quote, font=fonts["sub"], fill=(210, 228, 248))
    if len(data) > top_n:
        draw.text((R - 270, H - 55), f"仅显示前{top_n}位，共{len(data)}位",
                  font=fonts["sub"], fill=(174, 202, 236))

    img_path = config.image_dir / f"{group_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{title_suffix.replace(' ', '_')}.png"
    img_path.parent.mkdir(exist_ok=True)
    img.save(str(img_path), "PNG", optimize=True)
    return img_path


def generate_activity_line_chart(
    daily_data: list[tuple[str, int, int]],
    group_id: int, day_count: int, config: Config
) -> Path:
    """生成每日发言折线图"""
    vertical_mode = day_count > 30
    if not vertical_mode:
        width, height = 1280, 780
        ml, mr, mt, mb = 90, 50, 170, 150
    else:
        width = 1280
        row_gap = 20 if day_count <= 60 else (16 if day_count <= 120 else (12 if day_count <= 240 else 10))
        height = max(980, 230 + day_count * row_gap + 130)
        ml, mr, mt, mb = 250, 80, 170, 130

    pw, ph = width - ml - mr, height - mt - mb
    img = Image.new("RGB", (width, height), "#0F1F3A")
    draw = ImageDraw.Draw(img)

    for y in range(height):
        t = y / max(1, height - 1)
        draw.line([(0, y), (width, y)],
                  fill=(int(13 + 20 * t), int(31 + 40 * t), int(58 + 60 * t)))

    font_path = config.resolve_font_path()
    def _tf(sz):
        try:
            return ImageFont.truetype(font_path, sz) if font_path else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()

    title_font = _tf(42)
    sub_font = _tf(24)
    axis_font = _tf(20 if not vertical_mode else (16 if day_count <= 120 else 13))
    value_font = _tf(18 if not vertical_mode else (14 if day_count <= 120 else 12))
    dl_size = 18 if day_count <= 7 else (15 if day_count <= 14 else (13 if day_count <= 21 else 12))
    al_size = 15 if day_count <= 7 else (13 if day_count <= 14 else (11 if day_count <= 21 else 10))
    date_label_font = _tf(dl_size)
    active_label_font = _tf(al_size)

    draw.text((60, 24), f"群 {group_id} 近{day_count}天活跃趋势", fill=(245, 250, 255), font=title_font)
    sd = daily_data[0][0] if daily_data else "-"
    ed = daily_data[-1][0] if daily_data else datetime.now(config.tz).strftime("%Y-%m-%d")
    draw.text((60, 74), f"统计维度：每日发言次数  |  起始：{sd}  截止：{ed}",
              fill=(176, 203, 240), font=sub_font)

    x1, y1 = ml, mt
    x2, y2 = ml + pw, mt + ph
    draw.rounded_rectangle((x1 - 18, y1 - 18, x2 + 18, y2 + 18), radius=24,
                           fill=(31, 55, 88), outline=(180, 210, 245), width=2)

    counts = [msg_cnt for _, msg_cnt, _ in daily_data]
    max_count = max(counts) if counts else 1
    x_top = max(5, int(max_count * 1.15))
    n = len(daily_data)

    if not vertical_mode:
        for i in range(6):
            gy = y1 + int(ph * i / 5)
            val = int(x_top * (5 - i) / 5)
            draw.line([(x1, gy), (x2, gy)], fill=(95, 120, 160), width=1)
            draw.text((20, gy - 10), str(val), fill=(195, 216, 246), font=axis_font)
        draw.line([(x1, y1), (x1, y2)], fill=(210, 230, 255), width=2)
        draw.line([(x1, y2), (x2, y2)], fill=(210, 230, 255), width=2)
        step_x = pw if n <= 1 else pw / (n - 1)
        points = []
        for i, (day_s, cnt, active_cnt) in enumerate(daily_data):
            px = int(x1 + step_x * i)
            py = int(y2 - (cnt / x_top) * ph) if x_top > 0 else y2
            points.append((px, py))
            dbox = draw.textbbox((0, 0), day_s[5:], font=date_label_font)
            abox = draw.textbbox((0, 0), f"活跃{active_cnt}", font=active_label_font)
            draw.text((px - (dbox[2] - dbox[0]) // 2, y2 + 18),
                      day_s[5:], fill=(188, 210, 238), font=date_label_font)
            draw.text((px - (abox[2] - abox[0]) // 2, y2 + 38),
                      f"活跃{active_cnt}", fill=(155, 202, 239), font=active_label_font)
        if points:
            draw.polygon([(points[0][0], y2)] + points + [(points[-1][0], y2)],
                         fill=(82, 176, 255, 65))
            draw.line(points, fill=(93, 197, 255), width=5)
            for px, py in points:
                draw.ellipse((px - 6, py - 6, px + 6, py + 6),
                             fill=(255, 255, 255), outline=(59, 149, 235), width=2)
            for i, (px, py) in enumerate(points):
                draw.text((px - 10, py - 30), str(daily_data[i][1]),
                          fill=(230, 241, 255), font=value_font)
    else:
        for i in range(7):
            gx = x1 + int(pw * i / 6)
            val = int(x_top * i / 6)
            draw.line([(gx, y1), (gx, y2)], fill=(95, 120, 160), width=1)
            vb = draw.textbbox((0, 0), str(val), font=axis_font)
            draw.text((gx - (vb[2] - vb[0]) // 2, y2 + 12), str(val),
                      fill=(195, 216, 246), font=axis_font)
        draw.line([(x1, y1), (x1, y2)], fill=(210, 230, 255), width=2)
        draw.line([(x1, y2), (x2, y2)], fill=(210, 230, 255), width=2)
        step_y = ph if n <= 1 else ph / (n - 1)
        points = []
        for i, (day_s, cnt, active_cnt) in enumerate(daily_data):
            py = int(y1 + step_y * i)
            px = int(x1 + (cnt / x_top) * pw) if x_top > 0 else x1
            points.append((px, py))
            draw.text((38, py - 10), day_s[5:], fill=(188, 210, 238), font=axis_font)
            draw.text((110, py - 10), f"活跃{active_cnt}", fill=(155, 202, 239), font=axis_font)
            draw.line([(x1, py), (x2, py)], fill=(68, 93, 132), width=1)
        if points:
            draw.line(points, fill=(93, 197, 255), width=4)
            for idx, (px, py) in enumerate(points):
                draw.ellipse((px - 4, py - 4, px + 4, py + 4),
                             fill=(255, 255, 255), outline=(59, 149, 235), width=2)
                draw.text((px + 8, py - 10), str(daily_data[idx][1]),
                          fill=(230, 241, 255), font=value_font)

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
    draw.text((60, height - 90), summary, fill=(204, 223, 248), font=sub_font)

    out_dir = Path("activity_images")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{group_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_active_{day_count}d.png"
    img.save(str(out_path), "PNG", optimize=True)
    return out_path
