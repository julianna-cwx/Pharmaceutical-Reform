"""
新增医院数据 - 高德坐标补全专用脚本

固定流程：
输入：D:\Hospital_Pharmacy program\data\hospital\hosp_registered_data\ol_data\02_added_hospital_baidu.csv
输出：D:\Hospital_Pharmacy program\data\hospital\hosp_registered_data\ol_data\03_added_hospital_baidu_gaode.csv
缓存：D:\Hospital_Pharmacy program\data\hospital\hosp_registered_data\ol_data\added_gaode_geocode_cache.csv
失败记录：D:\Hospital_Pharmacy program\data\hospital\hosp_registered_data\ol_data\gaode_geocode_failed_detail.csv

运行示例：
    python datacleaning_gaode_added_hospital.py --workers 1 --min-interval 0.5 --realtime-cache

试跑前100条：
    python datacleaning_gaode_added_hospital_clean.py --limit 100 --workers 1 --min-interval 0.5 --realtime-cache
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import signal
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import requests

try:
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover
    class _TqdmFallback:  # pragma: no cover
        def __init__(self, it=None, **_kwargs):
            self.it = it
        def __iter__(self):
            if self.it is None:
                return iter(())
            return iter(self.it)
        def update(self, _n: int = 1) -> None:
            return None
        def close(self) -> None:
            return None
        def __enter__(self):
            return self
        def __exit__(self, _exc_type, _exc, _tb):
            self.close()
            return False
    def tqdm(it=None, **kwargs):  # type: ignore
        return _TqdmFallback(it, **kwargs)


BASE_DIR = Path(r"D:\Hospital_Pharmacy program\data\hospital\hosp_registered_data\ol_data")
INPUT_FILE = BASE_DIR / "02_added_hospital_baidu.csv"
OUTPUT_FILE = BASE_DIR / "03_added_hospital_baidu_gaode.csv"
CACHE_FILE = BASE_DIR / "added_gaode_geocode_cache.csv"
FAILED_FILE = BASE_DIR / "gaode_geocode_failed_detail.csv"

DEFAULT_GAODE_KEYS: list[str] = [
    "71eda588d66a45f49f79933945d97570",
    "3d650f19f641eaf57fd37d849617d6d3",
]


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def read_csv_with_fallback(path: Path | str, *, encodings: Sequence[str] | None = None, **kwargs: Any) -> pd.DataFrame:
    """读取 CSV，并自动尝试多种中文常见编码。"""
    path_obj = Path(path)
    candidates = list(encodings) if encodings else ["utf-8-sig", "utf-8", "gb18030", "gbk", "cp936", "latin-1"]
    last_exc: UnicodeDecodeError | None = None
    for encoding in candidates:
        try:
            df = pd.read_csv(path_obj, encoding=encoding, low_memory=False, **kwargs)
            if encoding != candidates[0]:
                print(f"[编码提示] {path_obj.name} 使用 {encoding} 编码读取")
            return df
        except UnicodeDecodeError as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        tried = ", ".join(candidates)
        raise UnicodeDecodeError(
            last_exc.encoding or "utf-8",
            last_exc.object,
            last_exc.start,
            last_exc.end,
            f"{last_exc.reason}; 尝试编码: {tried}; 文件: {path_obj}",
        ) from last_exc
    raise RuntimeError(f"读取 {path_obj} 失败，未找到可用编码")


def clean_hospital_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r"[（(].*?[)）]", "", name)
    name = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", name)
    return name.strip()


def build_address_candidates(row: pd.Series) -> list[str]:
    province = _safe_str(row.get("省份", ""))
    area = _safe_str(row.get("地区", ""))
    entname = _safe_str(row.get("ENTNAME", ""))
    cleaned_name = clean_hospital_name(entname)

    candidates: list[str] = []
    if province and area and entname:
        candidates.append(f"{province}{area}{entname}")
    if province and entname:
        candidates.append(f"{province}{entname}")
    if area and entname:
        candidates.append(f"{area}{entname}")
    if province and area and cleaned_name:
        candidates.append(f"{province}{area}{cleaned_name}")
    if province and cleaned_name:
        candidates.append(f"{province}{cleaned_name}")
    if entname:
        candidates.append(entname)
    if cleaned_name and cleaned_name != entname:
        candidates.append(cleaned_name)

    seen: set[str] = set()
    result: list[str] = []
    for addr in candidates:
        if addr and addr not in seen:
            seen.add(addr)
            result.append(addr)
    return result


def load_cache(cache_path: Path) -> dict[str, tuple[float | None, float | None]]:
    if not cache_path.exists():
        print("未发现高德缓存，重新开始")
        return {}

    cache_df = read_csv_with_fallback(cache_path)
    required = {"address", "lng", "lat"}
    if not required.issubset(cache_df.columns):
        print("缓存缺少 address/lng/lat 字段，忽略此缓存重新构建")
        return {}

    cache: dict[str, tuple[float | None, float | None]] = {}
    success_count = 0
    failed_count = 0
    for row in cache_df.itertuples(index=False):
        address = _safe_str(getattr(row, "address", ""))
        lng = getattr(row, "lng", None)
        lat = getattr(row, "lat", None)
        if isinstance(lng, float) and pd.isna(lng):
            lng = None
        if isinstance(lat, float) and pd.isna(lat):
            lat = None
        if address:
            cache[address] = (lng, lat)
            if lng is not None and lat is not None:
                success_count += 1
            else:
                failed_count += 1
    print(f"已加载高德缓存 {len(cache)} 条（成功: {success_count}, 失败: {failed_count}）")
    return cache


def append_single_cache_row(cache_path: Path, address: str, lng: float | None, lat: float | None, lock: threading.Lock) -> None:
    with lock:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        has_header = cache_path.exists() and cache_path.stat().st_size > 0
        with cache_path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if not has_header:
                writer.writerow(["address", "lng", "lat"])
            writer.writerow([address, "" if lng is None else lng, "" if lat is None else lat])


@dataclass
class _KeyState:
    key: str
    session: requests.Session
    last_request_ts: float = 0.0
    cooldown_until: float = 0.0
    in_flight: bool = False
    disabled: bool = False
    disabled_reason: str = ""
    request_count: int = 0


class GaodeGeocoder:
    def __init__(
        self,
        api_keys: Sequence[str],
        *,
        trust_env: bool,
        timeout: float,
        min_interval: float,
        max_attempts: int,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
    ) -> None:
        self._timeout = float(timeout)
        self._min_interval = max(float(min_interval), 0.2)
        self._max_attempts = max(int(max_attempts), 1)
        self._backoff_base = max(float(backoff_base), 0.5)
        self._backoff_max = max(float(backoff_max), self._backoff_base)
        self._lock = threading.Lock()

        keys: list[_KeyState] = []
        for raw_key in api_keys:
            clean_key = raw_key.strip()
            if not clean_key:
                continue
            session = requests.Session()
            session.trust_env = trust_env
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            })
            keys.append(_KeyState(key=clean_key, session=session))
        if not keys:
            raise ValueError("未提供有效的高德 API Key，请使用 --api-key 或设置 GAODE_API_KEYS 环境变量")
        self._keys = keys
        print(f"初始化 {len(keys)} 个高德 Key")

    def _acquire_key(self) -> tuple[_KeyState | None, float]:
        now = time.monotonic()
        with self._lock:
            if all(k.disabled for k in self._keys):
                return None, 0.0
            candidates = [k for k in self._keys if (not k.disabled) and (not k.in_flight)]
            if not candidates:
                return None, 0.1
            def next_ready(k: _KeyState) -> float:
                extra_cooldown = 5.0 if k.request_count > 0 and k.request_count % 300 == 0 else 0.0
                return max(k.cooldown_until, k.last_request_ts + self._min_interval + extra_cooldown)
            best = min(candidates, key=next_ready)
            ready_at = next_ready(best)
            if ready_at > now:
                return None, min(ready_at - now, 1.0)
            best.in_flight = True
            best.last_request_ts = now
            best.request_count += 1
            return best, 0.0

    def _release_key(self, key: _KeyState) -> None:
        with self._lock:
            key.in_flight = False

    def _cooldown_key(self, key: _KeyState, seconds: float) -> None:
        until = time.monotonic() + max(float(seconds), 0.0)
        with self._lock:
            key.cooldown_until = max(key.cooldown_until, until)

    def _disable_key(self, key: _KeyState, reason: str) -> None:
        with self._lock:
            if not key.disabled:
                print(f"\n[警告] 高德 Key 被禁用 {key.key[:8]}..., 原因: {reason}")
            key.disabled = True
            key.disabled_reason = reason[:200]
            key.cooldown_until = float("inf")

    def _request(self, key: _KeyState, address: str) -> tuple[float | None, float | None, str, str]:
        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {"address": address, "key": key.key, "output": "JSON"}
        try:
            resp = key.session.get(url, params=params, timeout=self._timeout)
            if resp.status_code != 200:
                return None, None, f"http_{resp.status_code}", ""
            data = resp.json()
        except requests.Timeout:
            return None, None, "timeout", "请求超时"
        except requests.RequestException as exc:
            return None, None, "request_error", str(exc)[:100]
        except Exception as exc:
            return None, None, "bad_json", str(exc)[:100]

        status = str(data.get("status", ""))
        info = str(data.get("info", ""))
        infocode = str(data.get("infocode", ""))
        if status == "1":
            geocodes = data.get("geocodes") or []
            if geocodes:
                location = _safe_str(geocodes[0].get("location", ""))
                parts = location.split(",")
                if len(parts) == 2:
                    try:
                        return float(parts[0]), float(parts[1]), "0", ""
                    except ValueError:
                        pass
            return None, None, "empty", "geocodes_empty"
        return None, None, infocode or status, info

    def geocode_multi_strategy(self, address_list: list[str]) -> tuple[float | None, float | None, str, str]:
        if not address_list:
            return None, None, "", "empty_address_list"
        last_error = ""
        for candidate in address_list:
            if not candidate:
                continue
            for attempt in range(self._max_attempts):
                key, wait_s = self._acquire_key()
                if key is None:
                    if wait_s > 0:
                        time.sleep(wait_s)
                        continue
                    return None, None, "", last_error or "no_valid_keys"
                try:
                    lng, lat, status, msg = self._request(key, candidate)
                except Exception as exc:
                    last_error = f"request_exception:{type(exc).__name__}"
                    backoff = min(self._backoff_max, self._backoff_base * (2 ** attempt))
                    self._cooldown_key(key, backoff)
                    continue
                finally:
                    self._release_key(key)
                if lng is not None and lat is not None:
                    return lng, lat, candidate, ""
                status_str = str(status)
                last_error = f"status={status_str} {msg}".strip()
                if status_str in {"10001", "10002", "10003", "10004", "10005"}:
                    self._disable_key(key, last_error)
                    continue
                over_limit = "OVER_LIMIT" in msg.upper()
                if status_str in {"10006", "10007", "10008", "10009"} or over_limit:
                    backoff = min(60.0, self._backoff_base * (2 ** (attempt + 2)))
                    self._cooldown_key(key, backoff)
                    continue
                backoff = min(self._backoff_max, self._backoff_base * (2 ** attempt))
                self._cooldown_key(key, backoff)
            time.sleep(0.1)
        return None, None, "", last_error or "all_strategies_failed"


def resolve_api_keys(cli_keys: Sequence[str] | None) -> list[str]:
    candidates: list[str] = []
    if cli_keys:
        candidates.extend(cli_keys)
    env_value = os.environ.get("GAODE_API_KEYS", "")
    if env_value.strip():
        candidates.extend(part.strip() for part in env_value.split(","))
    candidates.extend(DEFAULT_GAODE_KEYS)

    cleaned: list[str] = []
    seen: set[str] = set()
    for key in candidates:
        key = key.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(key)
    if not cleaned:
        raise ValueError("未提供任何高德 API Key，可通过 --api-key 或 GAODE_API_KEYS 设置")
    return cleaned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="新增医院数据：高德坐标补全")
    parser.add_argument("--input", default=None, help=f"输入 CSV 路径，默认 {INPUT_FILE}")
    parser.add_argument("--output", default=None, help=f"输出 CSV 路径，默认 {OUTPUT_FILE}")
    parser.add_argument("--cache", default=None, help=f"缓存 CSV 路径，默认 {CACHE_FILE}")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个缺失高德坐标的数据")
    parser.add_argument("--trust-env", action="store_true", help="使用系统代理，默认不使用")
    parser.add_argument("--workers", type=int, default=1, help="并发线程数，建议 1-2")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时时间，单位秒")
    parser.add_argument("--min-interval", type=float, default=0.5, help="单 Key 请求最小间隔，单位秒")
    parser.add_argument("--max-attempts", type=int, default=5, help="单个地址最大尝试次数")
    parser.add_argument("--retry-rounds", type=int, default=3, help="失败地址重试轮数")
    parser.add_argument("--save-interval", type=int, default=50, help="每处理 N 条保存一次结果")
    parser.add_argument("--realtime-cache", action="store_true", help="实时写入缓存 CSV，推荐开启")
    parser.add_argument("--start-from", type=int, default=0, help="从第 N 行开始处理，用于断点续跑")
    parser.add_argument("--api-key", action="append", default=None, help="高德 Key，可重复指定多次")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_csv_path = Path(args.input).expanduser().resolve() if args.input else INPUT_FILE
    output_csv_path = Path(args.output).expanduser().resolve() if args.output else OUTPUT_FILE
    cache_path = Path(args.cache).expanduser().resolve() if args.cache else CACHE_FILE

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if args.limit:
        output_csv_path = output_csv_path.with_name(f"{output_csv_path.stem}_preview_{args.limit}{output_csv_path.suffix}")
    if not input_csv_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_csv_path}")
    if input_csv_path.suffix.lower() != ".csv":
        raise ValueError(f"仅支持 CSV 文件，当前文件: {input_csv_path}")

    print(f"\n{'=' * 60}")
    print(f"读取数据: {input_csv_path}")
    df = read_csv_with_fallback(input_csv_path)
    print(f"文件总行数: {len(df)}")
    print(f"字段: {df.columns.tolist()}")

    lng_col = "高德经度"
    lat_col = "高德纬度"
    for col in [lng_col, lat_col]:
        if col not in df.columns:
            df[col] = float("nan")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    cache = load_cache(cache_path)
    cache_write_lock = threading.Lock()

    need_mask = df[lng_col].isna() | df[lat_col].isna()
    if args.start_from > 0:
        start_mask = pd.Series([False] * args.start_from + [True] * max(len(df) - args.start_from, 0), index=df.index)
        need_mask = need_mask & start_mask
    need_indices = df.index[need_mask].tolist()
    if args.limit and len(need_indices) > args.limit:
        print(f"检测到 --limit {args.limit}，仅处理前 {args.limit} 条缺失高德坐标数据")
        need_indices = need_indices[: args.limit]

    print(f"\n{'=' * 60}")
    print(f"文件中缺失高德坐标的总行数: {int(need_mask.sum())}")
    print(f"本次需要查询的行数: {len(need_indices)}")
    print(f"{'=' * 60}\n")

    if not need_indices:
        print("所有数据都已有高德坐标，无需查询")
        df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
        print(f"结果已保存到: {output_csv_path}")
        return 0

    geocoder = GaodeGeocoder(
        resolve_api_keys(args.api_key),
        trust_env=bool(args.trust_env),
        timeout=float(args.timeout),
        min_interval=float(args.min_interval),
        max_attempts=int(args.max_attempts),
    )

    total_processed = 0
    total_success = 0
    total_failed = 0
    failed_records: list[dict[str, Any]] = []
    results_saved = False
    interrupted = False

    def save_dataframe(tag: str) -> None:
        df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
        print(f"\n[{tag}] 已保存到: {output_csv_path}")
        if failed_records:
            pd.DataFrame(failed_records).to_csv(FAILED_FILE, index=False, encoding="utf-8-sig")
            print(f"[失败记录] 已保存到: {FAILED_FILE} ({len(failed_records)} 条)")

    def signal_handler(_signum, _frame):
        nonlocal interrupted
        if interrupted:
            print("\n\n强制退出...")
            sys.exit(1)
        interrupted = True
        print("\n\n检测到中断信号，正在保存当前结果...")
        save_dataframe("中断保存")
        current_success = int((df[lng_col].notna() & df[lat_col].notna()).sum())
        print(f"当前进度: 已完成 {total_processed} 条查询，有高德坐标 {current_success} 条")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    def process_row(idx: int) -> tuple[int, bool, str]:
        row = df.loc[idx]
        if pd.notna(row[lng_col]) and pd.notna(row[lat_col]):
            return idx, True, "already_exists"

        address_candidates = build_address_candidates(row)
        if not address_candidates:
            return idx, False, "no_valid_address"

        for addr in address_candidates:
            if addr in cache:
                cached_lng, cached_lat = cache[addr]
                if cached_lng is not None and cached_lat is not None:
                    df.loc[idx, lng_col] = cached_lng
                    df.loc[idx, lat_col] = cached_lat
                    return idx, True, f"cache:{addr}"

        lng, lat, success_addr, error = geocoder.geocode_multi_strategy(address_candidates)
        if lng is not None and lat is not None:
            df.loc[idx, lng_col] = lng
            df.loc[idx, lat_col] = lat
            if success_addr:
                cache[success_addr] = (lng, lat)
                if args.realtime_cache:
                    append_single_cache_row(cache_path, success_addr, lng, lat, cache_write_lock)
            return idx, True, success_addr

        for addr in address_candidates:
            cache[addr] = (None, None)
            if args.realtime_cache:
                append_single_cache_row(cache_path, addr, None, None, cache_write_lock)
        return idx, False, f"failed: {error}"

    retry_rounds = max(1, int(args.retry_rounds))
    current_indices = need_indices.copy()

    try:
        for round_num in range(1, retry_rounds + 1):
            if not current_indices:
                print(f"\n第 {round_num} 轮无待查询数据")
                break
            print(f"\n{'=' * 60}")
            print(f"第 {round_num} 轮高德查询开始")
            print(f"待查询行数: {len(current_indices)}")
            print(f"{'=' * 60}\n")

            round_success = 0
            round_failed = 0
            failed_indices: list[int] = []
            workers = max(1, int(args.workers))
            save_interval = max(50, int(args.save_interval))

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(process_row, idx): idx for idx in current_indices}
                with tqdm(total=len(current_indices), desc=f"第{round_num}轮高德查询") as pbar:
                    completed = 0
                    while futures:
                        done, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                        if not done:
                            continue
                        for fut in done:
                            idx = futures.pop(fut)
                            try:
                                _, success, used_addr = fut.result()
                                total_processed += 1
                                completed += 1
                                if success:
                                    round_success += 1
                                else:
                                    round_failed += 1
                                    failed_indices.append(idx)
                                    row = df.loc[idx]
                                    failed_records.append({
                                        "index": idx,
                                        "companyid": _safe_str(row.get("companyid", "")),
                                        "ENTNAME": _safe_str(row.get("ENTNAME", "")),
                                        "省份": _safe_str(row.get("省份", "")),
                                        "地区": _safe_str(row.get("地区", "")),
                                        "error": used_addr,
                                    })
                                if completed % save_interval == 0:
                                    save_dataframe("中间结果")
                            except Exception as exc:
                                print(f"\n处理行 {idx} 时出错: {exc}")
                                failed_indices.append(idx)
                                round_failed += 1
                            pbar.update(1)

            total_success += round_success
            total_failed += round_failed
            print(f"\n第 {round_num} 轮完成:")
            print(f"  成功: {round_success}")
            print(f"  失败: {round_failed}")
            success_pct = (total_success * 100 // total_processed) if total_processed else 0
            print(f"  累计成功率: {total_success}/{total_processed} ({success_pct}%)")

            if round_num < retry_rounds and failed_indices:
                wait_time = min(10 * round_num, 30)
                print(f"\n准备第 {round_num + 1} 轮重试，剩余 {len(failed_indices)} 行")
                print(f"等待 {wait_time} 秒...")
                time.sleep(wait_time)
                current_indices = failed_indices
            else:
                break

        print(f"\n{'=' * 60}")
        save_dataframe("保存结果")
        results_saved = True
    except Exception as exc:
        print(f"\n\n发生异常: {exc}")
        print("正在保存当前结果...")
        if not results_saved:
            save_dataframe("异常保存")
            results_saved = True
        raise
    finally:
        if not results_saved and not interrupted:
            print("\n\n确保保存结果...")
            try:
                save_dataframe("最终保存")
            except Exception as exc:
                print(f"保存结果时出错: {exc}")

    final_success = int((df[lng_col].notna() & df[lat_col].notna()).sum())
    final_missing = len(df) - final_success
    print(f"\n{'=' * 60}")
    print("最终统计:")
    print(f"  总行数: {len(df)}")
    print(f"  有高德坐标: {final_success} ({final_success * 100 // len(df)}%)")
    print(f"  无高德坐标: {final_missing} ({final_missing * 100 // len(df)}%)")
    print(f"{'=' * 60}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
