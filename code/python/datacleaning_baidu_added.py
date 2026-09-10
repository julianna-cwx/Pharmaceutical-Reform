r"""
新增医院百度坐标查询脚本（精简版）

固定项目路径：
D:\Hospital_Pharmacy program\data\hospital\hosp_registered_data\ol_data

固定输入：
01_added_hospital_2022_not_in_policy.csv

固定输出：
02_added_hospital_baidu.csv

固定缓存：
added_baidu_geocode_cache.csv

运行示例：
python datacleaning_baidu_added_hospital.py --workers 1 --min-interval 0.8 --realtime-cache

试跑前 100 条：
python datacleaning_baidu_added_hospital.py --limit 100 --workers 1 --min-interval 0.8 --realtime-cache
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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
import urllib.parse

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


# =========================
# 固定路径设置
# =========================
BASE_DIR = Path(r"D:\Hospital_Pharmacy program\data\hospital\hosp_registered_data\ol_data")
INPUT_FILE = BASE_DIR / "03_added_hospital_baidu_gaode.csv"
OUTPUT_FILE = BASE_DIR / "03_added_hospital_baidu_gaode.csv"
CACHE_FILE = BASE_DIR / "added_baidu_geocode_cache.csv"
FAILED_FILE = BASE_DIR / "02_added_hospital_baidu_failed_detail.csv"
TEMP_FILE = BASE_DIR / "02_added_hospital_baidu_temp.csv"

API_KEYS: list[dict[str, str]] = [
 #{"ak": "FQZ1SXmCXnUN7HCo87tCCJ4zotrYwaZW", "sk": "122X3Ybl3LjrjIBEJMbUwEEHt2A9AuLU"}
# {"ak": "g7rj0AKqYtElGj4sI8HqPTnRDQ4wVyFj", "sk": "JMBTGzhwZviJZTjMv7ZXbv52PzyHcIvs"},
 #   {"ak": "cHAOhSdYCfVx5i8c150m2PACRuufKZQU", "sk": "H2b2YF9L7s7rlXqu2SGHLUaOEEwdpyCD"},
 {"ak": "88pVUFzwEfk91TH5jI8WnOMgkMnJFMuB", "sk": "D3JNsGHCPZ1kLsZOyTHWKk7gV0YGUmYn"}
# {"ak": "DpAzhY1zVy3TUgvzAT7nfhUwCrVdSXIg", "sk": "KvEE5RCW8STpVDlu2ROu95IT92N7SRm9"}

]


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if pd.isna(value):
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


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
    """
    Read a CSV file and try multiple encodings to avoid UnicodeDecodeError.
    """
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
    raise RuntimeError(f"读取 {path_obj} 失败，未返回可用的编码信息")


def clean_hospital_name(name: str) -> str:
    """清洗医院名称，去除无用信息"""
    if not name:
        return ""

    # 去除括号及其内容（中英文括号）
    name = re.sub(r'[（(].*?[)）]', '', name)

    # 去除特殊字符但保留中文、字母、数字
    name = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', name)

    return name.strip()


def build_address_candidates(row: pd.Series) -> list[str]:
    """
    为每一行数据构建多个地址候选项，按优先级排序
    返回的地址候选列表将依次尝试
    """
    province = _safe_str(row.get("省份", ""))
    area = _safe_str(row.get("地区", ""))
    entname = _safe_str(row.get("ENTNAME", ""))

    # 清洗医院名称
    cleaned_name = clean_hospital_name(entname)

    candidates = []

    # 策略1: 完整地址
    if province and area and entname:
        candidates.append(f"{province}{area}{entname}")

    # 策略2: 省份+医院名
    if province and entname:
        candidates.append(f"{province}{entname}")

    # 策略3: 地区+医院名
    if area and entname:
        candidates.append(f"{area}{entname}")

    # 策略4: 完整地址+清洗后的医院名
    if province and area and cleaned_name:
        candidates.append(f"{province}{area}{cleaned_name}")

    # 策略5: 省份+清洗后的医院名
    if province and cleaned_name:
        candidates.append(f"{province}{cleaned_name}")

    # 策略6: 只用医院名
    if entname:
        candidates.append(entname)

    # 策略7: 只用清洗后的医院名
    if cleaned_name and cleaned_name != entname:
        candidates.append(cleaned_name)

    # 去重并保持顺序
    seen = set()
    result = []
    for addr in candidates:
        if addr and addr not in seen:
            seen.add(addr)
            result.append(addr)

    return result


def load_cache(cache_path: Path) -> dict[str, tuple[float | None, float | None]]:
    """
    加载缓存，key是地址，value是(经度, 纬度)
    如果同一地址有多条记录，使用最后一条（最新的）
    """
    if not cache_path.exists():
        print("未发现缓存，重新开始")
        return {}

    cache_df = read_csv_with_fallback(cache_path)

    required = {"address", "lng", "lat"}
    if not required.issubset(set(cache_df.columns)):
        print("缓存文件缺少必要字段(address/lng/lat)，将忽略该缓存并重新开始")
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

    print(f"已加载缓存 {len(cache)} 条 (成功: {success_count}, 失败: {failed_count})")
    return cache


def append_single_cache_row(
    cache_path: Path,
    address: str,
    lng: float | None,
    lat: float | None,
    lock: threading.Lock
) -> None:
    """实时追加单条缓存记录（线程安全）"""
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
    ak: str
    sk: str
    session: requests.Session
    last_request_ts: float = 0.0
    cooldown_until: float = 0.0
    in_flight: bool = False
    disabled: bool = False
    disabled_reason: str = ""
    request_count: int = 0  # 新增：记录请求次数


class BaiduGeocoder:
    def __init__(
        self,
        api_keys: list[dict[str, str]],
        *,
        trust_env: bool,
        timeout: float,
        min_interval: float,
        max_attempts: int,
        backoff_base: float = 1.0,  # 增加基础退避时间
        backoff_max: float = 30.0,  # 增加最大退避时间
    ) -> None:
        self._timeout = float(timeout)
        self._min_interval = max(float(min_interval), 0.2)  # 最小间隔至少0.2秒
        self._max_attempts = max(int(max_attempts), 1)
        self._backoff_base = max(float(backoff_base), 0.5)
        self._backoff_max = max(float(backoff_max), self._backoff_base)
        self._lock = threading.Lock()

        keys: list[_KeyState] = []
        for key in api_keys:
            ak = str(key.get("ak", "")).strip()
            sk = str(key.get("sk", "")).strip()
            if not ak or not sk:
                continue
            session = requests.Session()
            session.trust_env = trust_env
            # 添加请求头，模拟正常浏览器
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
            })
            keys.append(_KeyState(ak=ak, sk=sk, session=session))
        if not keys:
            raise ValueError("未提供有效的 Baidu API_KEYS (ak/sk)")
        self._keys = keys
        print(f"初始化 {len(keys)} 个 API Key")

    def _acquire_key(self) -> tuple[_KeyState | None, float]:
        """获取可用的API Key"""
        now = time.monotonic()
        with self._lock:
            if all(k.disabled for k in self._keys):
                return None, 0.0

            candidates = [k for k in self._keys if (not k.disabled) and (not k.in_flight)]
            if not candidates:
                return None, 0.1

            def next_ready(k: _KeyState) -> float:
                # 每100个请求后，增加额外的冷却时间
                extra_cooldown = 0.0
                if k.request_count > 0 and k.request_count % 100 == 0:
                    extra_cooldown = 5.0  # 每100个请求休息5秒
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
            if not key.disabled:  # 只在第一次禁用时打印
                print(f"\n[警告] API Key 被禁用: {key.ak[:10]}... 原因: {reason}")
            key.disabled = True
            key.disabled_reason = str(reason)[:200]
            key.cooldown_until = float("inf")

    def _request(
        self,
        key: _KeyState,
        address: str
    ) -> tuple[float | None, float | None, Any, str]:
        """发送地理编码请求"""
        sn = get_sn(address, key.ak, key.sk)
        url = (
            "https://api.map.baidu.com/geocoding/v3/"
            f"?address={urllib.parse.quote(address, safe='')}"
            f"&output=json&ak={key.ak}&ret_coordtype=bd09ll&sn={sn}"
        )

        try:
            r = key.session.get(url, timeout=self._timeout)
            if r.status_code != 200:
                return None, None, f"http_{r.status_code}", ""

            data = r.json()
        except requests.Timeout:
            return None, None, "timeout", "请求超时"
        except requests.RequestException as e:
            return None, None, "request_error", str(e)[:100]
        except Exception as e:
            return None, None, "bad_json", str(e)[:100]

        status = data.get("status")
        if status == 0 or status == "0":
            loc = (data.get("result") or {}).get("location") or {}
            lng = loc.get("lng")
            lat = loc.get("lat")
            if lng is not None and lat is not None:
                return lng, lat, status, ""

        msg = data.get("message") or data.get("msg") or ""
        return None, None, status, str(msg)

    def geocode_multi_strategy(
        self,
        address_list: list[str]
    ) -> tuple[float | None, float | None, str, str]:
        """
        使用多策略尝试地理编码
        address_list: 按优先级排序的地址列表
        返回: (lng, lat, 成功的地址, 错误信息)
        """
        if not address_list:
            return None, None, "", "empty_address_list"

        last_error = ""

        # 对每个地址候选进行尝试
        for candidate in address_list:
            if not candidate:
                continue

            for attempt in range(self._max_attempts):
                key, wait_s = self._acquire_key()
                if key is None:
                    if wait_s > 0:
                        time.sleep(wait_s)
                        continue
                    return None, None, "", last_error or "no_valid_api_keys"

                try:
                    lng, lat, status, msg = self._request(key, candidate)
                except Exception as e:
                    last_error = f"request_exception:{type(e).__name__}"
                    backoff = min(self._backoff_max, self._backoff_base * (2**attempt))
                    self._cooldown_key(key, backoff)
                    continue
                finally:
                    self._release_key(key)

                # 成功获取坐标
                if lng is not None and lat is not None:
                    return lng, lat, candidate, ""

                status_str = str(status)
                last_error = f"status={status_str} {msg}".strip()

                # API key 失效（AK/SK错误），禁用该key
                if status_str in {"302", "2", "3"}:
                    self._disable_key(key, last_error or f"status={status_str}")
                    continue

                # 401并发超限 - 长时间冷却而不是禁用
                if status_str == "401":
                    backoff = min(60.0, self._backoff_base * (2**(attempt + 3)))
                    print(f"\n[警告] 并发超限，冷却 {backoff:.0f} 秒")
                    self._cooldown_key(key, backoff)
                    continue

                # 配额超限，长时间冷却
                if status_str in {"403", "4"}:
                    backoff = min(30.0, self._backoff_base * (2**(attempt + 2)))
                    self._cooldown_key(key, backoff)
                    continue

                # 其他错误，短时间冷却
                backoff = min(self._backoff_max, self._backoff_base * (2**attempt))
                self._cooldown_key(key, backoff)

            # 该地址候选失败，尝试下一个
            # 在候选之间添加小延迟
            time.sleep(0.1)

        return None, None, "", last_error or "all_strategies_failed"


def get_sn(address: str, ak: str, sk: str) -> str:
    """生成百度API签名"""
    query_str = f"/geocoding/v3/?address={address}&output=json&ak={ak}&ret_coordtype=bd09ll"
    encoded_str = urllib.parse.quote(query_str, safe="/:=&?#+!$,;'@()*[]")
    raw_str = encoded_str + sk
    return hashlib.md5(urllib.parse.quote_plus(raw_str).encode("utf-8")).hexdigest()




def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="新增医院百度坐标查询：固定读取 01_added_hospital_2022_not_in_policy.csv")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 个缺失坐标的数据，用于试跑")
    parser.add_argument("--trust-env", action="store_true", help="使用系统代理，默认不使用")
    parser.add_argument("--workers", type=int, default=1, help="并发线程数。建议 1，避免百度 API 限流")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒数")
    parser.add_argument("--min-interval", type=float, default=0.8, help="单个 AK 请求最小间隔秒数")
    parser.add_argument("--max-attempts", type=int, default=5, help="单个地址候选的最大重试次数")
    parser.add_argument("--retry-rounds", type=int, default=3, help="失败地址重试轮数")
    parser.add_argument("--save-interval", type=int, default=50, help="每处理 N 条保存一次临时结果")
    parser.add_argument("--realtime-cache", action="store_true", help="实时写入缓存，强烈推荐")
    parser.add_argument("--start-from", type=int, default=0, help="从第 N 行开始处理，用于断点续传")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    BASE_DIR.mkdir(parents=True, exist_ok=True)

    input_csv_path = INPUT_FILE
    output_csv_path = OUTPUT_FILE if not args.limit else BASE_DIR / f"02_added_hospital_baidu_preview_{args.limit}.csv"
    cache_path = CACHE_FILE

    if not input_csv_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_csv_path}")

    print(f"\n{'='*60}")
    print(f"工作目录: {BASE_DIR}")
    print(f"输入文件: {input_csv_path}")
    print(f"输出文件: {output_csv_path}")
    print(f"缓存文件: {cache_path}")
    print(f"{'='*60}\n")

    df = read_csv_with_fallback(input_csv_path)

    print(f"文件总行数: {len(df)}")
    print(f"字段: {df.columns.tolist()}")

    if "ENTNAME" not in df.columns:
        raise KeyError("输入文件缺少 ENTNAME 列，无法构建医院名称查询地址")

    for col in ["百度经度", "百度纬度"]:
        if col not in df.columns:
            df[col] = float("nan")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    cache = load_cache(cache_path)
    cache_write_lock = threading.Lock()

    lng_col = "百度经度"
    lat_col = "百度纬度"

    need_mask = df[lng_col].isna() | df[lat_col].isna()
    if args.start_from > 0:
        start_mask = pd.Series(
            [False] * min(args.start_from, len(df)) + [True] * max(len(df) - args.start_from, 0),
            index=df.index,
        )
        need_mask = need_mask & start_mask

    need_indices = df.index[need_mask].tolist()

    if args.limit and len(need_indices) > args.limit:
        print(f"检测到 --limit {args.limit}，仅处理前 {args.limit} 条缺失坐标记录")
        need_indices = need_indices[:args.limit]

    print(f"\n{'='*60}")
    print(f"文件中缺失百度坐标的总行数: {int(need_mask.sum())}")
    print(f"本次需要查询的行数: {len(need_indices)}")
    print(f"{'='*60}\n")

    if not need_indices:
        print("所有数据都已有百度坐标，无需查询。")
        df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
        print(f"文件保存至: {output_csv_path}")
        return 0

    geocoder = BaiduGeocoder(
        API_KEYS,
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

    def save_current_results() -> None:
        df.to_csv(TEMP_FILE, index=False, encoding="utf-8-sig")
        print(f"\n[中间结果] 已保存到: {TEMP_FILE}")

    def save_final_results() -> None:
        df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
        print(f"\n[保存结果] 已保存到: {output_csv_path}")
        if failed_records:
            pd.DataFrame(failed_records).to_csv(FAILED_FILE, index=False, encoding="utf-8-sig")
            print(f"[失败记录] 已保存到: {FAILED_FILE} ({len(failed_records)} 条)")

    def signal_handler(signum, frame) -> None:
        nonlocal interrupted
        if interrupted:
            print("\n\n强制退出...")
            sys.exit(1)
        interrupted = True
        print("\n\n检测到中断信号，正在保存当前结果...")
        save_final_results()
        print("结果已保存，可稍后重新运行脚本继续补坐标。")
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
                print(f"\n第 {round_num} 轮：无待查询数据")
                break

            print(f"\n{'='*60}")
            print(f"第 {round_num} 轮查询开始")
            print(f"待查询行数: {len(current_indices)}")
            print(f"{'='*60}\n")

            round_success = 0
            round_failed = 0
            failed_indices: list[int] = []

            workers = max(1, int(args.workers))
            save_interval = max(1, int(args.save_interval))

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
                                        "companyid": _safe_str(row.get("companyid", "")),
                                        "ENTNAME": _safe_str(row.get("ENTNAME", "")),
                                        "省份": _safe_str(row.get("省份", "")),
                                        "地区": _safe_str(row.get("地区", "")),
                                        "注册地址": _safe_str(row.get("注册地址", row.get("DOM", ""))),
                                        "error": used_addr,
                                    })

                                if completed % save_interval == 0:
                                    save_current_results()

                            except Exception as e:
                                print(f"\n处理行 {idx} 时出错: {e}")
                                failed_indices.append(idx)
                                round_failed += 1
                            pbar.update(1)

            total_success += round_success
            total_failed += round_failed

            print(f"\n第 {round_num} 轮完成:")
            print(f"  成功: {round_success}")
            print(f"  失败: {round_failed}")
            print(f"  累计成功率: {total_success}/{total_processed} ({total_success*100//total_processed if total_processed else 0}%)")

            if round_num < retry_rounds and failed_indices:
                wait_time = min(10 * round_num, 30)
                print(f"\n准备第 {round_num + 1} 轮重试，剩余 {len(failed_indices)} 行；等待 {wait_time} 秒...")
                time.sleep(wait_time)
                current_indices = failed_indices
            else:
                break

        print(f"\n{'='*60}")
        save_final_results()
        results_saved = True

    except Exception as e:
        print(f"\n\n发生异常: {e}")
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
            except Exception as e:
                print(f"保存结果时出错: {e}")

    final_success = int((df[lng_col].notna() & df[lat_col].notna()).sum())
    final_missing = len(df) - final_success

    print(f"\n{'='*60}")
    print("最终统计:")
    print(f"  总行数: {len(df)}")
    print(f"  有百度坐标: {final_success} ({final_success*100//len(df)}%)")
    print(f"  无百度坐标: {final_missing} ({final_missing*100//len(df)}%)")
    print(f"{'='*60}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
