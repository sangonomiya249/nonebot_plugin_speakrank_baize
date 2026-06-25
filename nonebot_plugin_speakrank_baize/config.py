"""发言排行插件 - 配置项"""
from pathlib import Path
from datetime import timedelta, timezone
from typing import Optional

# 插件内置字体路径（优先使用，把 .ttf 放在 speak_rank 目录下即可）
_PLUGIN_DIR = Path(__file__).parent
_BUILTIN_FONT = _PLUGIN_DIR / "font.ttf"

# 系统备选字体
_SYSTEM_FONTS = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


class Config:
    """发言排行插件配置（可通过 .env 或 WebUI 插件管理修改）"""

    # ── 数据存储 ──
    data_path: Path = Path("data/activity_stat")  # SQLite 数据库存放目录，相对路径基于 Bot 启动目录；pip 安装建议改为绝对路径
    db_path: Path = data_path / "activity_stat.db"  # 数据库文件完整路径，由 data_path 自动拼接

    # ── 字体 ──
    font_path: str = str(_BUILTIN_FONT)  # 首选字体路径：将 .ttf 放到插件目录改名为 font.ttf 即可，无需修改此项
    font_fallback_paths: list = _SYSTEM_FONTS  # 备选字体列表：内置字体不存在时按顺序查找系统字体（Windows/Linux/macOS）

    # ── 时区 ──
    timezone_name: str = "Asia/Shanghai"  # 统计时区名称，用于定时任务触发时间和日期计算

    @property
    def tz(self) -> timezone:  # 返回 timezone 对象供内部使用，由 timezone_name 控制
        return timezone(timedelta(hours=8))

    # ── 图片输出 ──
    image_dir: Path = Path("activity_images")  # 生成的排行图片和折线图存放目录

    # ── 图片尺寸（像素）──
    rank_image_width: int = 1080  # 排行榜卡片图宽度
    rank_image_height: int = 1260  # 排行榜卡片图高度

    # ── 定时任务 ──
    daily_rank_hour: int = 23  # 每日排行发送：几点触发 (0-23)
    daily_rank_minute: int = 15  # 每日排行发送：几分触发 (0-59)
    weekly_chart_hour: int = 23  # 每周趋势图发送：几点触发 (0-23)，仅周日执行
    weekly_chart_minute: int = 30  # 每周趋势图发送：几分触发 (0-59)

    # ── 每日一言 ──
    daily_quote_url: str = "https://api.tangdouz.com/a/one.php?return=json"  # 图片底部语录 API 地址，返回 JSON 需包含 tangdouz 字段
    daily_quote_max_length: int = 34  # 语录最大显示字数，超出自动截断

    # ── 排行限制 ──
    max_display_rank: int = 10  # 排行榜图片最多显示前 N 名
    max_query_days: int = 365  # 发言排行命令允许查询的最大天数

    # ── 安全发图 ──
    image_wait_max: float = 3.0  # 图片文件就绪等待最长时间（秒），防止文件未写完就发送
    image_wait_step: float = 0.15  # 每次检查文件是否就绪的间隔（秒）

    def resolve_font_path(self) -> Optional[str]:
        """按优先级查找可用的字体文件路径（内置 → 系统）"""
        paths = [self.font_path] + list(self.font_fallback_paths)
        for p in paths:
            if Path(p).exists():
                return p
        return None
