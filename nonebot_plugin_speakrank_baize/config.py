"""发言排行插件 - 配置项（支持 .env 覆盖）"""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path
from typing import Optional

from nonebot import logger

# 插件目录
_PLUGIN_DIR = Path(__file__).parent

# 插件内置字体路径
_BUILTIN_FONT = _PLUGIN_DIR / "font.ttf"

# 系统备选字体
_SYSTEM_FONTS = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]

# ═══════════════════ .env 覆盖支持 ═══════════════════

_ENV_PREFIX = "SPEAKRANK_"
# 兜底：如果被意外写成 tuple（如尾逗号），取第一个元素
if isinstance(_ENV_PREFIX, tuple):
    _ENV_PREFIX = str(_ENV_PREFIX[0]) if _ENV_PREFIX else "SPEAKRANK_"

_env_values: dict = {}
_root = Path.cwd()
for _env_file in [_root / ".env", _root / f".env.{os.environ.get('ENVIRONMENT', '')}"]:
    try:
        if _env_file.exists():
            for _line in _env_file.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if not _line or _line.startswith("#"):
                    continue
                _m = re.match(r'^([A-Z_][A-Z0-9_]*)\s*=\s*(.+)$', _line)
                if _m:
                    _env_values[_m.group(1)] = _m.group(2).strip().strip('"').strip("'")
    except Exception:
        pass

logger.info(f"[发言排行] 已从 {_root} 加载环境变量，找到 {len(_env_values)} 个 SPEAKRANK_ 配置项")


def _env(key: str, default):
    """优先读 .env (SPEAKRANK_XXX)，否则用默认值"""
    val = _env_values.get(f"{_ENV_PREFIX}{key}")
    if val is not None and val.strip():
        if isinstance(default, bool):
            return val.lower() in ("true", "1", "yes")
        if isinstance(default, int):
            return int(val)
        if isinstance(default, float):
            return float(val)
        if isinstance(default, list):
            return [x.strip() for x in val.split(",") if x.strip()]
        return val
    return default


# ═══════════════════ 配置数据类 ═══════════════════

@dataclass
class Config:
    """发言排行插件配置（可通过 .env 或 WebUI 插件管理修改）

    .env 覆盖格式: SPEAKRANK_<字段名大写>=<值>
    示例:
        SPEAKRANK_DATA_PATH=data/activity_stat
        SPEAKRANK_MAX_DISPLAY_RANK=15
        SPEAKRANK_DAILY_RANK_HOUR=20
    """

    # ── 数据存储 ──
    data_path: Path = field(default_factory=lambda: Path(_env("DATA_PATH", "data/activity_stat")))  # SQLite 数据库存放目录

    @property
    def db_path(self) -> Path:
        """数据库文件完整路径，由 data_path 自动拼接"""
        return self.data_path / "activity_stat.db"

    # ── 字体 ──
    font_path: str = field(default_factory=lambda: _env("FONT_PATH", str(_BUILTIN_FONT)))  # 首选字体路径
    font_fallback_paths: list = field(default_factory=lambda: _env("FONT_FALLBACK_PATHS", _SYSTEM_FONTS))  # 备选字体列表

    # ── 时区 ──
    timezone_name: str = field(default_factory=lambda: _env("TIMEZONE_NAME", "Asia/Shanghai"))  # 统计时区名称

    @property
    def tz(self) -> timezone:
        return timezone(timedelta(hours=8))

    # ── 群聊发送模式 ──
    send_mode: str = field(default_factory=lambda: _env("MODE", "whitelist"))  # "whitelist"(仅白名单群) / "blacklist"(所有群，黑名单例外)

    # ── 图片输出 ──
    image_dir: Path = field(default_factory=lambda: Path(_env("IMAGE_DIR", "activity_images")))  # 生成的排行图片和折线图存放目录

    # ── 图片尺寸（像素）──
    rank_image_width: int = field(default_factory=lambda: _env("RANK_IMAGE_WIDTH", 1080))  # 排行榜卡片图宽度
    rank_image_height: int = field(default_factory=lambda: _env("RANK_IMAGE_HEIGHT", 1260))  # 排行榜卡片图高度

    # ── 定时任务 ──
    daily_rank_hour: int = field(default_factory=lambda: _env("DAILY_RANK_HOUR", 23))  # 每日排行发送：几点触发 (0-23)
    daily_rank_minute: int = field(default_factory=lambda: _env("DAILY_RANK_MINUTE", 15))  # 每日排行发送：几分触发 (0-59)
    weekly_chart_hour: int = field(default_factory=lambda: _env("WEEKLY_CHART_HOUR", 23))  # 每周趋势图发送：几点触发，仅周日执行
    weekly_chart_minute: int = field(default_factory=lambda: _env("WEEKLY_CHART_MINUTE", 30))  # 每周趋势图发送：几分触发

    # ── 每日一言 ──
    daily_quote_url: str = field(default_factory=lambda: _env("DAILY_QUOTE_URL", "https://api.tangdouz.com/a/one.php?return=json"))  # 图片底部语录 API 地址
    daily_quote_max_length: int = field(default_factory=lambda: _env("DAILY_QUOTE_MAX_LENGTH", 34))  # 语录最大显示字数

    # ── 排行限制 ──
    max_display_rank: int = field(default_factory=lambda: _env("MAX_DISPLAY_RANK", 10))  # 排行榜图片最多显示前 N 名
    max_query_days: int = field(default_factory=lambda: _env("MAX_QUERY_DAYS", 365))  # 发言排行命令允许查询的最大天数

    # ── 安全发图 ──
    image_wait_max: float = field(default_factory=lambda: _env("IMAGE_WAIT_MAX", 3.0))  # 图片文件就绪等待最长时间（秒）
    image_wait_step: float = field(default_factory=lambda: _env("IMAGE_WAIT_STEP", 0.15))  # 每次检查文件是否就绪的间隔（秒）

    def resolve_font_path(self) -> Optional[str]:
        """按优先级查找可用的字体文件路径（内置 → 系统）"""
        paths = [self.font_path] + list(self.font_fallback_paths)
        for p in paths:
            if Path(p).exists():
                return p
        return None


# ═══════════════════ 全局配置实例 ═══════════════════
# WebUI 通过此实例识别和编辑配置

CONFIG = Config(
    data_path=Path(_env("DATA_PATH", 'data/activity_stat')),  # SQLite 数据库存放目录
    font_path=_env("FONT_PATH", str(_BUILTIN_FONT)),  # 首选字体路径
    font_fallback_paths=_env("FONT_FALLBACK_PATHS", _SYSTEM_FONTS),  # 备选字体列表
    timezone_name=_env("TIMEZONE_NAME", 'Asia/Shanghai'),  # 统计时区名称
    send_mode=_env("MODE", "whitelist"),  # 群聊发送模式: blacklist(默认所有群) / whitelist(仅白名单)
    image_dir=Path(_env("IMAGE_DIR", 'activity_images')),  # 生成的排行图片和折线图存放目录
    rank_image_width=_env("RANK_IMAGE_WIDTH", 1080),  # 排行榜卡片图宽度
    rank_image_height=_env("RANK_IMAGE_HEIGHT", 1260),  # 排行榜卡片图高度
    daily_rank_hour=_env("DAILY_RANK_HOUR", 23),  # 每日排行发送：几点触发 (0-23)
    daily_rank_minute=_env("DAILY_RANK_MINUTE", 15),  # 每日排行发送：几分触发 (0-59)
    weekly_chart_hour=_env("WEEKLY_CHART_HOUR", 23),  # 每周趋势图发送：几点触发，仅周日执行
    weekly_chart_minute=_env("WEEKLY_CHART_MINUTE", 30),  # 每周趋势图发送：几分触发
    daily_quote_url=_env("DAILY_QUOTE_URL", 'https://api.tangdouz.com/a/one.php?return=json'),  # 图片底部语录 API 地址
    daily_quote_max_length=_env("DAILY_QUOTE_MAX_LENGTH", 34),  # 语录最大显示字数
    max_display_rank=_env("MAX_DISPLAY_RANK", 10),  # 排行榜图片最多显示前 N 名
    max_query_days=_env("MAX_QUERY_DAYS", 365),  # 发言排行命令允许查询的最大天数
    image_wait_max=_env("IMAGE_WAIT_MAX", 3),  # 图片文件就绪等待最长时间（秒）
    image_wait_step=_env("IMAGE_WAIT_STEP", 0.15),  # 每次检查文件是否就绪的间隔（秒）
)

# ═══════════════════ 群聊名单管理 ═══════════════════
_PLUGIN_DATA_DIR = _PLUGIN_DIR / "data"
_LIST_FILE = _PLUGIN_DATA_DIR / "group_list.json"


def _load_list() -> dict:
    """加载群聊黑白名单。"""
    if _LIST_FILE.exists():
        try:
            return json.loads(_LIST_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"whitelist": [], "blacklist": []}


def _save_list(data: dict):
    """保存群聊黑白名单。"""
    _PLUGIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _LIST_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_whitelist(gid: int) -> bool:
    """添加群聊到白名单。"""
    data = _load_list()
    if gid not in data["whitelist"]:
        data["whitelist"].append(gid)
        _save_list(data)
        return True
    return False


def remove_whitelist(gid: int) -> bool:
    """从白名单移除群聊。"""
    data = _load_list()
    if gid in data["whitelist"]:
        data["whitelist"].remove(gid)
        _save_list(data)
        return True
    return False


def add_blacklist(gid: int) -> bool:
    """添加群聊到黑名单。"""
    data = _load_list()
    if gid not in data["blacklist"]:
        data["blacklist"].append(gid)
        _save_list(data)
        return True
    return False


def remove_blacklist(gid: int) -> bool:
    """从黑名单移除群聊。"""
    data = _load_list()
    if gid in data["blacklist"]:
        data["blacklist"].remove(gid)
        _save_list(data)
        return True
    return False


def should_send_to_group(gid: int) -> bool:
    """根据当前模式判断是否应该向该群发送统计图。"""
    data = _load_list()
    if CONFIG.send_mode == "whitelist":
        return int(gid) in data["whitelist"]
    else:
        return int(gid) not in data["blacklist"]


def reload_config():
    """运行时重新读取 .env，刷新 CONFIG 实例（供 WebUI 热重载）"""
    global _env_values, CONFIG
    _env_values.clear()
    for _env_file in [_root / ".env", _root / f".env.{os.environ.get('ENVIRONMENT', '')}"]:
        try:
            if _env_file.exists():
                for _line in _env_file.read_text(encoding="utf-8").splitlines():
                    _line = _line.strip()
                    if not _line or _line.startswith("#"):
                        continue
                    _m = re.match(r'^([A-Z_][A-Z0-9_]*)\s*=\s*(.+)$', _line)
                    if _m:
                        _env_values[_m.group(1)] = _m.group(2).strip().strip('"').strip("'")
        except Exception:
            pass
    CONFIG = Config(
        data_path=Path(_env("DATA_PATH", "data/activity_stat")),
        font_path=_env("FONT_PATH", str(_BUILTIN_FONT)),
        font_fallback_paths=_env("FONT_FALLBACK_PATHS", _SYSTEM_FONTS),
        timezone_name=_env("TIMEZONE_NAME", "Asia/Shanghai"),
        send_mode=_env("MODE", "blacklist"),
        image_dir=Path(_env("IMAGE_DIR", "activity_images")),
        rank_image_width=_env("RANK_IMAGE_WIDTH", 1080),
        rank_image_height=_env("RANK_IMAGE_HEIGHT", 1260),
        daily_rank_hour=_env("DAILY_RANK_HOUR", 23),
        daily_rank_minute=_env("DAILY_RANK_MINUTE", 15),
        weekly_chart_hour=_env("WEEKLY_CHART_HOUR", 23),
        weekly_chart_minute=_env("WEEKLY_CHART_MINUTE", 30),
        daily_quote_url=_env("DAILY_QUOTE_URL", "https://api.tangdouz.com/a/one.php?return=json"),
        daily_quote_max_length=_env("DAILY_QUOTE_MAX_LENGTH", 34),
        max_display_rank=_env("MAX_DISPLAY_RANK", 10),
        max_query_days=_env("MAX_QUERY_DAYS", 365),
        image_wait_max=_env("IMAGE_WAIT_MAX", 3.0),
        image_wait_step=_env("IMAGE_WAIT_STEP", 0.15),
    )
    _sync_plugin_config()
    logger.info("[发言排行] CONFIG 已从 .env 重新加载，WebUI 修改即时生效")


def _sync_plugin_config():
    """同步更新 __init__ 模块中的 plugin_config 引用"""
    try:
        import sys
        _mod = sys.modules.get(__name__.rsplit(".", 1)[0])
        if _mod is None:
            _mod = sys.modules.get(__name__.replace("config", "").rstrip("."))
        if _mod and hasattr(_mod, "plugin_config"):
            _mod.plugin_config = CONFIG
    except Exception:
        pass
