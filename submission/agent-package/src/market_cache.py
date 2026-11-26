#!/usr/bin/env python3
from contextlib import contextmanager
import argparse
from datetime import date, datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "state" / "market-data"


def trading_date(value):
    if isinstance(value, int) and not isinstance(value, bool):
        value = datetime.strptime(str(value), "%Y%m%d").date().isoformat()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("日线日期必须为 YYYY-MM-DD 或券商 YYYYMMDD 整数")
    return date.fromisoformat(value).isoformat()


def identity(symbol, autype=1, extended_time=0, source="moomoo"):
    if not re.fullmatch(r"US\.[A-Z0-9]+", symbol):
        raise ValueError("日线缓存仅支持 US 股票代码")
    if (autype not in (0, 1, 2) or extended_time not in (0, 1, 2)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", source)):
        raise ValueError("行情来源、复权或交易时段无效")
    return dict(source=source, symbol=symbol, ktype=2, autype=autype,
                extended_time=extended_time, timezone="America/New_York")


def cache_path(directory, series):
    return Path(directory) / (
        f"{series['symbol']}.day.a{series['autype']}.e{series['extended_time']}.{series['source']}.json"
    )


def load(path, series):
    if not path.exists():
        return dict(series=series, valid=True, bars=[])
    cached = json.loads(path.read_text())
    if cached["series"] != series:
        raise ValueError("缓存身份与请求不一致")
    return cached


@contextmanager
def writer(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def save(path, cached):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(cached, handle, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def plan(directory, series, through, min_bars=55):
    through = trading_date(through)
    if not 1 <= min_bars <= 370:
        raise ValueError("初始化根数必须在 1–370 之间")
    path = cache_path(directory, series)
    cached = load(path, series)
    rows = [bar for bar in cached["bars"] if bar["date"] <= through]
    request = {field: series[field] for field in ("symbol", "ktype", "autype", "extended_time")}
    request["end"] = through
    action = "cached"
    if not cached["valid"]:
        action = "rebuild"
        request.update(start=cached["bars"][0]["date"], num=370)
    elif len(rows) < min_bars:
        action = "bootstrap"
        request["num"] = min_bars
    elif rows[-1]["date"] < through:
        action = "incremental"
        request.update(start=rows[-1]["date"], num=370)
    return dict(action=action, path=str(path.resolve()), series=series, cached_bars=len(rows),
                last_date=rows[-1]["date"] if rows else None,
                request=None if action == "cached" else request)


def normalize(response, through):
    if not isinstance(response, dict) or response.get("ret_code") != 0:
        raise ValueError("只接受 ret_code=0 的券商原始日线响应")
    data = response.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("kline_list"), list):
        raise ValueError("缺少 data.kline_list")
    rows = {}
    for bar in data["kline_list"]:
        if not isinstance(bar, dict):
            raise ValueError("日线记录格式无效")
        day = trading_date(bar.get("date"))
        if day > through:
            raise ValueError("不得将未确认收盘或未来日线写入历史缓存")
        values = [bar.get(field) for field in ("open", "high", "low", "close", "volume")]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in values):
            raise ValueError("OHLCV 缺失或非有限数值")
        opening, high, low, close, volume = values
        if low <= 0 or low > min(opening, close) or high < max(opening, close) or volume < 0:
            raise ValueError("OHLCV 数值关系无效")
        row = dict(bar, date=day)
        if day in rows and rows[day] != row:
            raise ValueError("同一响应包含冲突的重复日期")
        rows[day] = row
    if not rows:
        raise ValueError("空响应不能推进缓存日期")
    return [rows[day] for day in sorted(rows)]


def merge(directory, series, response, through, rebuild=False):
    through = trading_date(through)
    rows = normalize(response, through)
    path = cache_path(directory, series)
    observed_at = datetime.now(timezone.utc).isoformat()
    with writer(path):
        cached = load(path, series)
        if not cached["valid"] and not rebuild:
            raise ValueError("历史复权基准已失效，必须完整重建缓存")
        old = {bar["date"]: bar for bar in cached["bars"]}
        new = {bar["date"]: bar for bar in rows}
        if rebuild and not old.keys() <= new.keys():
            raise ValueError("重建必须覆盖原有完整历史窗口，不得丢弃旧历史")
        if not rebuild and old and max(old) not in new:
            raise ValueError("增量更新必须包含上一根已收盘日线以校验复权基准")
        fields = ("open", "high", "low", "close", "volume")
        if (not rebuild and series["autype"] != 0
                and any(old[day][field] != new[day][field]
                        for day in old.keys() & new.keys() for field in fields)):
            save(path, dict(cached, valid=False))
            raise ValueError("重叠日线发生修订，已禁用旧缓存；请完整重建同一复权历史窗口")
        combined = new if rebuild else old | new
        save(path, dict(series=series, valid=True, observed_at=observed_at,
                        bars=[combined[day] for day in sorted(combined)]))
    return dict(path=str(path.resolve()), merged_bars=len(rows), total_bars=len(combined),
                last_date=max(combined), observed_at=observed_at)


def read(directory, series, through, min_bars=55):
    through = trading_date(through)
    if not 1 <= min_bars <= 370:
        raise ValueError("所需根数必须在 1–370 之间")
    path = cache_path(directory, series)
    cached = load(path, series)
    rows = [bar for bar in cached["bars"] if bar["date"] <= through]
    if not cached["valid"]:
        raise ValueError("历史复权基准失效，缓存不可用于信号计算")
    if len(rows) < min_bars or rows[-1]["date"] != through:
        raise ValueError("历史根数不足或未覆盖指定已收盘交易日")
    return dict(path=str(path.resolve()), series=series, observed_at=cached["observed_at"],
                dates=[bar["date"] for bar in rows],
                bars={field: [bar[name] for bar in rows]
                      for field, name in (("o", "open"), ("h", "high"), ("l", "low"),
                                          ("c", "close"), ("v", "volume"))})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "merge", "read"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--through", required=True, help="经市场日历确认的最后已收盘交易日")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--autype", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--extended-time", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--source", default="moomoo")
    parser.add_argument("--min-bars", type=int, default=55)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    try:
        series = identity(args.symbol, args.autype, args.extended_time, args.source)
        if args.action == "merge":
            output = merge(args.cache_dir, series, json.load(sys.stdin), args.through, args.rebuild)
        elif args.action == "plan":
            output = plan(args.cache_dir, series, args.through, args.min_bars)
        else:
            output = read(args.cache_dir, series, args.through, args.min_bars)
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
