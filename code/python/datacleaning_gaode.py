"""
22版医院工商数据的后续处理 - 高德坐标补全（独立脚本）

特性概览：
1. 复用 datacleaning_baidu.py 的地址构建、断点续传、失败分析等逻辑；
2. 调用高德 Web 服务地理编码 API（REST）补全高德坐标；
3. 支持限流、实时缓存与多轮重试；
4. 默认输出 hospital_geocode_gaode_result.csv，避免覆盖百度产物。
5. 默认输入 hospital_geocode_result.csv，并可复用上次输出文件增量续跑，避免重复查询。

用法示例：
    python datacleaning_gaode.py --workers 4 --min-interval 0.5 --realtime-cache
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Sequence

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

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


DEFAULT_INPUT_NAME = "hospital_geocode_result.csv"
DEFAULT_OUTPUT_NAME = "hospital_geocode_gaode_result.csv"
DEFAULT_CACHE_NAME = "gaode_geocode_cache.csv"
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


def read_csv_with_fallback(
    path: Path | str,
    *,
    encodings: Sequence[str] | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Read a CSV file while trying multiple encodings."""

    path_obj = Path(path)
    candidates = list(encodings) if encodings else [
        "utf-8-sig",
        "utf-8",
        "gb18030",
        "gbk",
        "cp936",
        "latin-1",
    ]
    last_exc: UnicodeDecodeError | None = None
    for encoding in candidates:
        try:
            df = pd.read_csv(path_obj, encoding=encoding, **kwargs)
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


def find_latest_input_excel(
    base_dir: Path,
    *,
    initial_input_name: str = DEFAULT_INPUT_NAME,
) -> Path:
    if initial_input_name:
        initial_candidate = base_dir / initial_input_name
        if initial_candidate.exists():
            print(f"[固定输入] 使用默认输入文件: {initial_candidate.name}")
            return initial_candidate

    raise FileNotFoundError(
        f"未在目录 {base_dir} 中找到可用输入文件。预期: {initial_input_name}"
    )


def load_cache(cache_path: Path) -> dict[str, tuple[float | None, float | None]]:
    if not cache_path.exists():
        print("未发现缓存，重新开始")
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
    print(f"已加载缓存 {len(cache)} 条(成功: {success_count}, 失败: {failed_count})")
    return cache


def append_single_cache_row(
    cache_path: Path,
    address: str,
    lng: float | None,
    lat: float | None,
    lock: threading.Lock,
) -> None:
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
                extra_cooldown = 0.0
                if k.request_count > 0 and k.request_count % 300 == 0:
                    extra_cooldown = 5.0
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
                print(f"\n[警告] Key 被禁用 {key.key[:8]}..., 原因: {reason}")
            key.disabled = True
            key.disabled_reason = reason[:200]
            key.cooldown_until = float("inf")

    def _request(self, key: _KeyState, address: str) -> tuple[float | None, float | None, str, str]:
        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {
            "address": address,
            "key": key.key,
            "output": "JSON",
        }
        try:
            resp = key.session.get(url, params=params, timeout=self._timeout)
            if resp.status_code != 200:
                return None, None, f"http_{resp.status_code}", ""
            data = resp.json()
        except requests.Timeout:
            return None, None, "timeout", "请求超时"
        except requests.RequestException as exc:
            return None, None, "request_error", str(exc)[:100]
        except Exception as exc:  # pragma: no cover
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
                        lng = float(parts[0])
                        lat = float(parts[1])
                        return lng, lat, "0", ""
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
                except Exception as exc:  # pragma: no cover
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
    parser = argparse.ArgumentParser(description="22版医院工商数据清洗：高德坐标补全")
    parser.add_argument("--base-dir", default=None, help="工作目录(默认脚本所在目录)")
    parser.add_argument("--input", default=None, help="输入 CSV/XLSX 路径(默认自动使用 hospital_geocode_result.csv)")
    parser.add_argument("--output", default=None, help="输出 CSV 路径(默认 hospital_geocode_gaode_result.csv)")
    parser.add_argument("--cache", default=None, help="缓存 CSV 路径(默认 gaode_geocode_cache.csv)")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个缺失坐标的数据")
    parser.add_argument("--trust-env", action="store_true", help="使用系统代理(默认不使用)")
    parser.add_argument("--workers", type=int, default=2, help="并发线程数(建议 1-2)")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时时间(秒)")
    parser.add_argument("--min-interval", type=float, default=0.5, help="单 Key 请求最小间隔(秒)")
    parser.add_argument("--max-attempts", type=int, default=5, help="单个地址最大尝试次数")
    parser.add_argument("--retry-rounds", type=int, default=3, help="失败地址的重试轮数")
    parser.add_argument("--save-interval", type=int, default=50, help="每处理 N 条保存一次结果")
    parser.add_argument("--realtime-cache", action="store_true", help="实时写入缓存 CSV")
    parser.add_argument("--start-from", type=int, default=0, help="从第 N 行开始处理(断点续跑)")
    parser.add_argument("--api-key", action="append", default=None, help="高德 Key，可重复指定多次")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve() if args.base_dir else Path(__file__).resolve().parent
    os.makedirs(base_dir, exist_ok=True)

    if args.output:
        output_csv_path = Path(args.output).expanduser().resolve()
    elif args.limit:
        default_output_path = Path(DEFAULT_OUTPUT_NAME)
        output_suffix = default_output_path.suffix or ".csv"
        output_csv_path = base_dir / f"{default_output_path.stem}_preview_{args.limit}{output_suffix}"
    else:
        output_csv_path = base_dir / DEFAULT_OUTPUT_NAME

    resume_from_output = False
    if not args.input and output_csv_path.exists():
        input_excel_path = output_csv_path
        resume_from_output = True
        print(f"[增量模式] 继续使用已有输出文件: {output_csv_path.name}")
    elif args.input:
        input_excel_path = Path(args.input).expanduser().resolve()
    else:
        input_excel_path = find_latest_input_excel(base_dir, initial_input_name=DEFAULT_INPUT_NAME)

    cache_path = Path(args.cache).expanduser().resolve() if args.cache else base_dir / DEFAULT_CACHE_NAME

    print(f"\n{'=' * 60}")
    print(f"读取数据: {input_excel_path}")
    file_suffix = input_excel_path.suffix.lower()
    if file_suffix == ".csv":
        df = read_csv_with_fallback(input_excel_path)
    elif file_suffix in [".xlsx", ".xls"]:
        df = pd.read_excel(input_excel_path)
    else:
        raise ValueError(f"不支持的文件格式: {file_suffix}, 仅支持 CSV/XLSX")

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

    need_mask = (df[lng_col].isna() | df[lat_col].isna())
    if args.start_from > 0:
        start_mask = pd.Series([False] * args.start_from + [True] * (len(df) - args.start_from), index=df.index)
        need_mask = need_mask & start_mask

    need_indices = df.index[need_mask].tolist()
    if args.limit and len(need_indices) > args.limit:
        print(f"检测到 --limit {args.limit}，仅处理前 {args.limit} 条缺失坐标数据")
        need_indices = need_indices[: args.limit]

    print(f"\n{'=' * 60}")
    print(f"文件中缺失坐标的总行数: {int(need_mask.sum())}")
    print(f"本次需要查询的行数: {len(need_indices)}")
    print(f"{'=' * 60}\n")

    if not need_indices:
        print("所有数据都已有高德坐标，无需查询")
        df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
        print(f"结果已保存到: {output_csv_path}")
        return 0

    api_keys = resolve_api_keys(args.api_key)
    geocoder = GaodeGeocoder(
        api_keys,
        trust_env=bool(args.trust_env),
        timeout=float(args.timeout),
        min_interval=float(args.min_interval),
        max_attempts=int(args.max_attempts),
    )

    total_processed = 0
    total_success = 0
    total_failed = 0
    failed_records: list[dict[str, Any]] = []

    def persist_dataframe(tag: str) -> None:
        temp_path = output_csv_path.parent / f"{output_csv_path.stem}_temp{output_csv_path.suffix}"
        df.to_csv(temp_path, index=False, encoding="utf-8-sig")
        shutil.copyfile(temp_path, output_csv_path)
        print(f"\n[{tag}] 临时文件: {temp_path}")
        print(f"[{tag}] 已同步输出: {output_csv_path}")

    def save_current_results() -> None:
        persist_dataframe("中间结果")

    def save_final_results() -> None:
        persist_dataframe("保存结果")
        if failed_records:
            failed_path = base_dir / "gaode_geocode_failed_detail.csv"
            pd.DataFrame(failed_records).to_csv(failed_path, index=False, encoding="utf-8-sig")
            print(f"[失败记录] 已保存到: {failed_path} ({len(failed_records)} 条)")

    interrupted = False

    def signal_handler(_signum, _frame):
        nonlocal interrupted
        if interrupted:
            print("\n\n强制退出...")
            sys.exit(1)
        interrupted = True
        print("\n\n检测到中断信号，正在保存当前结果...")
        save_final_results()
        current_success = int((df[lng_col].notna() & df[lat_col].notna()).sum())
        print(f"当前进度: 已完成 {total_processed} 条查询，成功 {current_success} 条")
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

    retry_rounds = max(1, args.retry_rounds)
    current_indices = need_indices.copy()
    results_saved = False

    try:
        for round_num in range(1, retry_rounds + 1):
            if not current_indices:
                print(f"\n第 {round_num} 轮无待查询数据")
                break

            print(f"\n{'=' * 60}")
            print(f"第 {round_num} 轮查询开始")
            print(f"待查询行数: {len(current_indices)}")
            print(f"{'=' * 60}\n")

            round_success = 0
            round_failed = 0
            failed_indices: list[int] = []

            workers = max(1, int(args.workers))
            save_interval = max(50, int(args.save_interval))

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(process_row, idx): idx for idx in current_indices}

                with tqdm(total=len(current_indices), desc=f"第{round_num}轮查询") as pbar:
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
                                        "ENTNAME": _safe_str(row.get("ENTNAME", "")),
                                        "省份": _safe_str(row.get("省份", "")),
                                        "地区": _safe_str(row.get("地区", "")),
                                        "error": used_addr,
                                    })
                                if completed % save_interval == 0:
                                    save_current_results()
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
            print(f"  总成功率: {total_success}/{total_processed} ({success_pct}%)")

            if round_num < retry_rounds and failed_indices:
                print(f"\n准备第 {round_num + 1} 轮重试，剩余 {len(failed_indices)} 行")
                wait_time = min(10 * round_num, 30)
                print(f"等待 {wait_time} 秒...")
                time.sleep(wait_time)
                current_indices = failed_indices
            else:
                break

        print(f"\n{'=' * 60}")
        save_final_results()
        results_saved = True

    except Exception as exc:
        print(f"\n\n发生异常: {exc}")
        print("正在保存当前结果...")
        if not results_saved:
            save_final_results()
            results_saved = True
        raise
    finally:
        if not results_saved and not interrupted:
            print("\n\n确保保存结果...")
            try:
                save_final_results()
            except Exception as exc:
                print(f"保存结果时出错: {exc}")

    final_success = int((df[lng_col].notna() & df[lat_col].notna()).sum())
    final_missing = len(df) - final_success

    print(f"\n{'=' * 60}")
    print("最终统计:")
    print(f"  总行数: {len(df)}")
    print(f"  有坐标: {final_success} ({final_success * 100 // len(df)}%)")
    print(f"  无坐标: {final_missing} ({final_missing * 100 // len(df)}%)")
    print(f"{'=' * 60}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
