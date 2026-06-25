"""发言排行插件 - 数据库操作"""
import aiosqlite
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


async def init_db(db_path: Path):
    """初始化数据库表与索引"""
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS group_message (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nickname TEXT NOT NULL,
            time TEXT NOT NULL)''')
        await db.execute('''CREATE INDEX IF NOT EXISTS idx_group_time
            ON group_message (group_id, time)''')
        await db.commit()


async def insert_message(db_path: Path, group_id: int, user_id: int,
                         nickname: str, time_str: str):
    """插入一条发言记录"""
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "INSERT INTO group_message (group_id, user_id, nickname, time) VALUES (?, ?, ?, ?)",
            (group_id, user_id, nickname, time_str),
        )
        await db.commit()


async def get_distinct_groups(db_path: Path) -> list[int]:
    """获取所有记录过的群号"""
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute("SELECT DISTINCT group_id FROM group_message")
        return [row[0] for row in await cursor.fetchall()]


async def query_group_rank(db_path: Path, group_id: int,
                           start_time: datetime, end_time: datetime,
                           limit: int = 10) -> list[tuple]:
    """查询群内发言排行 [(user_id, nickname, count), ...]"""
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute('''
            SELECT user_id, COUNT(*) as count, MAX(time) as last_time
            FROM group_message
            WHERE group_id = ? AND time >= ? AND time < ?
            GROUP BY user_id
            ORDER BY count DESC
            LIMIT ?
        ''', (group_id,
              start_time.strftime("%Y-%m-%d %H:%M:%S"),
              end_time.strftime("%Y-%m-%d %H:%M:%S"),
              limit))

        results = []
        for row in await cursor.fetchall():
            user_id, count, last_time = row
            cursor2 = await db.execute(
                "SELECT nickname FROM group_message WHERE user_id = ? AND time = ? LIMIT 1",
                (user_id, last_time)
            )
            nickname_row = await cursor2.fetchone()
            nickname = nickname_row[0] if nickname_row else str(user_id)
            results.append((user_id, nickname, count))
        return results


async def query_historical_rank(db_path: Path, group_id: int,
                                limit: int = 10) -> list[tuple]:
    """查询群内历史总排行"""
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute('''
            SELECT user_id, COUNT(*) as count, MAX(time) as last_time
            FROM group_message
            WHERE group_id = ?
            GROUP BY user_id
            ORDER BY count DESC
            LIMIT ?
        ''', (group_id, limit))
        results = []
        for row in await cursor.fetchall():
            user_id, count, last_time = row
            cursor2 = await db.execute(
                "SELECT nickname FROM group_message WHERE user_id = ? AND time = ? LIMIT 1",
                (user_id, last_time)
            )
            nickname_row = await cursor2.fetchone()
            nickname = nickname_row[0] if nickname_row else str(user_id)
            results.append((user_id, nickname, count))
        return results


async def query_total_group_rank(db_path: Path, day_count: int = 30,
                                 limit: int = 20) -> list[tuple]:
    """查询所有群的发言排行 [(group_id, count), ...]"""
    now = datetime.now()
    start = now - timedelta(days=day_count)
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            '''SELECT group_id, COUNT(*) as count
               FROM group_message
               WHERE time >= ? AND time < ?
               GROUP BY group_id
               ORDER BY count DESC LIMIT ?''',
            (start.strftime("%Y-%m-%d %H:%M:%S"),
             now.strftime("%Y-%m-%d %H:%M:%S"), limit))
        return await cursor.fetchall()


async def query_historical_group_rank(db_path: Path,
                                      limit: int = 20) -> list[tuple]:
    """查询所有群历史总排行"""
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            '''SELECT group_id, COUNT(*) as count
               FROM group_message
               GROUP BY group_id ORDER BY count DESC LIMIT ?''', (limit,))
        return await cursor.fetchall()


async def query_group_period_stats(db_path: Path, group_id: int,
                                   start_time: datetime,
                                   end_time: datetime) -> tuple[int, int]:
    """查询本群指定时间段的总发言数与去重活跃人数"""
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            '''SELECT COUNT(*), COUNT(DISTINCT user_id)
               FROM group_message
               WHERE group_id = ? AND time >= ? AND time < ?''',
            (group_id,
             start_time.strftime("%Y-%m-%d %H:%M:%S"),
             end_time.strftime("%Y-%m-%d %H:%M:%S")))
        row = await cursor.fetchone()
    if not row:
        return 0, 0
    return int(row[0] or 0), int(row[1] or 0)


async def query_group_daily_counts(db_path: Path, group_id: int,
                                   day_count: int,
                                   tz) -> list[tuple[str, int, int]]:
    """查询近N天每日发言数和活跃人数 [(YYYY-MM-DD, 发言数, 活跃人数), ...]"""
    from datetime import datetime as dt
    now = dt.now(tz)
    today = now.date()
    start_day = today - timedelta(days=day_count - 1)
    start_dt = dt.combine(start_day, dt.min.time())
    end_dt = dt.combine(today + timedelta(days=1), dt.min.time())

    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            '''SELECT substr(time, 1, 10) as day, COUNT(*),
                      COUNT(DISTINCT user_id)
               FROM group_message
               WHERE group_id = ? AND time >= ? AND time < ?
               GROUP BY day ORDER BY day ASC''',
            (group_id,
             start_dt.strftime("%Y-%m-%d %H:%M:%S"),
             end_dt.strftime("%Y-%m-%d %H:%M:%S")))
        rows = await cursor.fetchall()

    count_map = {row[0]: (row[1], row[2]) for row in rows}
    out = []
    for i in range(day_count):
        d = start_day + timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        msg_cnt, active_cnt = count_map.get(ds, (0, 0))
        out.append((ds, int(msg_cnt), int(active_cnt)))
    return out


async def count_historical_active(db_path: Path,
                                  group_id: Optional[int] = None) -> int:
    """查询历史去重活跃人数（可指定群，不指定则查所有群）"""
    async with aiosqlite.connect(str(db_path)) as db:
        if group_id is not None:
            cursor = await db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM group_message WHERE group_id = ?",
                (group_id,))
        else:
            cursor = await db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM group_message")
        row = await cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


async def count_recent_active(db_path: Path, day_count: int = 30) -> int:
    """查询近N天所有群去重活跃人数"""
    now = datetime.now()
    start = now - timedelta(days=day_count)
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            '''SELECT COUNT(DISTINCT user_id) FROM group_message
               WHERE time >= ? AND time < ?''',
            (start.strftime("%Y-%m-%d %H:%M:%S"),
             now.strftime("%Y-%m-%d %H:%M:%S")))
        row = await cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0
