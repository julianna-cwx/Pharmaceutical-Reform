"""
22版医院工商数据的后续处理 - 改进版
主要改进：
1. 多策略地址构建：尝试多种地址组合方式提高查询成功率
2. 智能重试机制：对失败地址使用不同的地址格式重试
3. 更好的速率控制：避免被百度API封禁
4. 实时缓存：支持随时中断和恢复
5. 详细的失败分析：记录每个失败地址的所有尝试记录

使用方法：
python datacleaning_baidu.py --workers 4 --min-interval 0.3 --realtime-cache
"""



from __future__ import annotations
import argparse
import csv
import hashlib
import os
import random
import re
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Sequence
import urllib.parse

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


API_KEYS: list[dict[str, str]] = [
 {"ak": "FQZ1SXmCXnUN7HCo87tCCJ4zotrYwaZW", "sk": "122X3Ybl3LjrjIBEJMbUwEEHt2A9AuLU"}
#     {"ak": "g7rj0AKqYtElGj4sI8HqPTnRDQ4wVyFj", "sk": "JMBTGzhwZviJZTjMv7ZXbv52PzyHcIvs"},
#     {"ak": "cHAOhSdYCfVx5i8c150m2PACRuufKZQU", "sk": "H2b2YF9L7s7rlXqu2SGHLUaOEEwdpyCD"},
# {"ak": "88pVUFzwEfk91TH5jI8WnOMgkMnJFMuB", "sk": "D3JNsGHCPZ1kLsZOyTHWKk7gV0YGUmYn"}
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


def find_latest_input_excel(base_dir: Path, fresh_start: bool = False) -> Path:
    """
    查找最新的输入文件，优先级：
    1. hospital_geocode_result.csv (上次的输出，支持增量更新) - 除非 fresh_start=True
    2. fully_mapped_result_*.csv
    3. fully_mapped_result_*.xlsx
    """
    # 优先使用上次的输出文件（增量更新），除非用户指定从头开始
    if not fresh_start:
        result_file = base_dir / "hospital_geocode_result.csv"
        if result_file.exists():
            print(f"[增量模式] 使用上次的输出文件: {result_file.name}")
            print(f"提示: 使用 --fresh-start 参数可以从原始文件重新开始")
            return result_file

    # 先找 fully_mapped_result CSV
    csv_candidates = sorted(
        base_dir.glob("fully_mapped_result_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if csv_candidates:
        print(f"[全新模式] 使用原始输入文件: {csv_candidates[0].name}")
        return csv_candidates[0]

    # 如果没有 CSV，找 XLSX
    xlsx_candidates = sorted(
        base_dir.glob("fully_mapped_result_*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if xlsx_candidates:
        print(f"[全新模式] 使用原始输入文件: {xlsx_candidates[0].name}")
        return xlsx_candidates[0]

    # 都没有则报错
    raise FileNotFoundError(
        f"未在目录中找到输入文件: {base_dir}\n"
        f"期望匹配: hospital_geocode_result.csv, fully_mapped_result_*.csv 或 fully_mapped_result_*.xlsx"
    )


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
    parser = argparse.ArgumentParser(description="22版医院工商数据清洗：百度坐标补全（改进版）")
    parser.add_argument("--base-dir", default=None, help="工作目录(默认脚本所在目录)")
    parser.add_argument("--input", default=None, help="输入 CSV 路径(默认取最新 fully_mapped_result_*.csv)")
    parser.add_argument("--output", default=None, help="输出 CSV 路径(默认 hospital_geocode_result.csv)")
    parser.add_argument("--cache", default=None, help="缓存 CSV 路径(默认 geocode_cache.csv)")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 个缺失坐标的数据(用于试跑)")
    parser.add_argument(
        "--fresh-start",
        action="store_true",
        help="强制从原始文件开始(忽略已有的 hospital_geocode_result.csv)",
    )
    parser.add_argument(
        "--trust-env",
        action="store_true",
        help="使用系统代理(默认不使用)",
    )
    parser.add_argument("--workers", type=int, default=2, help="并发线程数(建议1-2，百度总QPS限制为3)")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时(秒)")
    parser.add_argument("--min-interval", type=float, default=0.8, help="单个AK请求最小间隔(秒，百度总QPS=3，建议0.8-1.0)")
    parser.add_argument("--max-attempts", type=int, default=5, help="单个地址的最大重试次数")
    parser.add_argument("--retry-rounds", type=int, default=3, help="失败地址的重试轮数")
    parser.add_argument("--save-interval", type=int, default=50, help="每处理N条后保存一次结果(默认50)")
    parser.add_argument("--realtime-cache", action="store_true", help="实时保存缓存(强烈推荐)")
    parser.add_argument("--start-from", type=int, default=0, help="从第N行开始处理(用于断点续传)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve() if args.base_dir else Path(__file__).resolve().parent
    os.makedirs(base_dir, exist_ok=True)

    input_excel_path = Path(args.input).expanduser().resolve() if args.input else find_latest_input_excel(base_dir, args.fresh_start)
    if args.output:
        output_csv_path = Path(args.output).expanduser().resolve()
    elif args.limit:
        output_csv_path = base_dir / f"hospital_geocode_result_preview_{args.limit}.csv"
    else:
        output_csv_path = base_dir / "hospital_geocode_result.csv"
    cache_path = Path(args.cache).expanduser().resolve() if args.cache else base_dir / "geocode_cache.csv"

    # 读取数据
    print(f"\n{'='*60}")
    print(f"读取数据: {input_excel_path}")
    # 注意：不管limit是多少，都读取完整文件，以便找到需要查询的行
    file_suffix = input_excel_path.suffix.lower()

    if file_suffix == '.csv':
        df = read_csv_with_fallback(input_excel_path)
    elif file_suffix in ['.xlsx', '.xls']:
        df = pd.read_excel(input_excel_path)
    else:
        raise ValueError(f"不支持的文件格式: {file_suffix}，仅支持 .csv, .xlsx, .xls")

    print(f"文件总行数: {len(df)}")
    print(f"字段: {df.columns.tolist()}")

    # 确保经纬度列存在
    for col in ["百度经度", "百度纬度"]:
        if col not in df.columns:
            df[col] = float("nan")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 加载缓存
    cache = load_cache(cache_path)
    cache_write_lock = threading.Lock()

    # 构建需要查询的行索引
    lng_col = "百度经度"
    lat_col = "百度纬度"

    # 找出需要查询的行（没有坐标的行）
    need_mask = (df[lng_col].isna() | df[lat_col].isna())
    if args.start_from > 0:
        # 支持断点续传
        start_mask = pd.Series([False] * args.start_from + [True] * (len(df) - args.start_from), index=df.index)
        need_mask = need_mask & start_mask

    need_indices = df.index[need_mask].tolist()

    # 如果指定了limit，只处理前N个需要查询的行
    if args.limit and len(need_indices) > args.limit:
        print(f"检测到 --limit {args.limit} 参数，只处理前 {args.limit} 个缺失坐标的数据")
        need_indices = need_indices[:args.limit]

    print(f"\n{'='*60}")
    print(f"文件中缺失坐标的总行数: {need_mask.sum()}")
    print(f"本次需要查询的行数: {len(need_indices)}")
    print(f"{'='*60}\n")

    if not need_indices:
        print("所有数据都已有坐标，无需查询！")
        df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
        print(f"文件保存至: {output_csv_path}")
        return 0

    # 初始化地理编码器
    geocoder = BaiduGeocoder(
        API_KEYS,
        trust_env=bool(args.trust_env),
        timeout=float(args.timeout),
        min_interval=float(args.min_interval),
        max_attempts=int(args.max_attempts),
    )

    # 统计信息
    total_processed = 0
    total_success = 0
    total_failed = 0

    # 失败记录
    failed_records: list[dict[str, Any]] = []

    def save_current_results():
        """保存当前结果到临时文件"""
        temp_path = output_csv_path.parent / f"{output_csv_path.stem}_temp{output_csv_path.suffix}"
        df.to_csv(temp_path, index=False, encoding="utf-8-sig")
        print(f"\n[中间结果] 已保存到: {temp_path}")

    def save_final_results():
        """保存最终结果到目标文件"""
        df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
        print(f"\n[保存结果] 已保存到: {output_csv_path}")

        # 保存失败记录
        if failed_records:
            failed_path = base_dir / "geocode_failed_detail.csv"
            pd.DataFrame(failed_records).to_csv(failed_path, index=False, encoding="utf-8-sig")
            print(f"[失败记录] 已保存到: {failed_path} ({len(failed_records)} 条)")

    # 信号处理：捕获中断信号(Ctrl+C)并保存结果
    interrupted = False

    def signal_handler(signum, frame):
        nonlocal interrupted
        if interrupted:
            print("\n\n强制退出...")
            sys.exit(1)

        interrupted = True
        print("\n\n检测到中断信号(Ctrl+C)，正在保存当前结果...")
        print("(再次按 Ctrl+C 强制退出)")
        save_final_results()

        # 显示当前进度
        current_success = int((df[lng_col].notna() & df[lat_col].notna()).sum())
        print(f"\n当前进度: 已完成 {total_processed} 条查询，成功 {current_success} 条")
        print(f"结果已安全保存，可以稍后使用 --start-from 参数继续")
        sys.exit(0)

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    def process_row(idx: int) -> tuple[int, bool, str]:
        """
        处理单行数据
        返回: (行索引, 是否成功, 使用的地址)
        """
        row = df.loc[idx]

        # 如果已有坐标，跳过
        if pd.notna(row[lng_col]) and pd.notna(row[lat_col]):
            return idx, True, "already_exists"

        # 构建地址候选列表
        address_candidates = build_address_candidates(row)

        if not address_candidates:
            return idx, False, "no_valid_address"

        # 首先检查缓存（检查所有候选地址）
        for addr in address_candidates:
            if addr in cache:
                cached_lng, cached_lat = cache[addr]
                if cached_lng is not None and cached_lat is not None:
                    df.loc[idx, lng_col] = cached_lng
                    df.loc[idx, lat_col] = cached_lat
                    return idx, True, f"cache:{addr}"

        # 使用多策略查询
        lng, lat, success_addr, error = geocoder.geocode_multi_strategy(address_candidates)

        if lng is not None and lat is not None:
            # 成功获取坐标
            df.loc[idx, lng_col] = lng
            df.loc[idx, lat_col] = lat

            # 更新缓存
            if success_addr:
                cache[success_addr] = (lng, lat)
                if args.realtime_cache:
                    append_single_cache_row(cache_path, success_addr, lng, lat, cache_write_lock)

            return idx, True, success_addr
        else:
            # 失败，记录所有尝试过的地址
            for addr in address_candidates:
                cache[addr] = (None, None)
                if args.realtime_cache:
                    append_single_cache_row(cache_path, addr, None, None, cache_write_lock)

            return idx, False, f"failed: {error}"

    # 多轮查询
    retry_rounds = max(1, args.retry_rounds)
    current_indices = need_indices.copy()
    results_saved = False  # 追踪结果是否已保存

    # 保持顺序，从第一个没有坐标的数据开始
    # random.shuffle(current_indices)  # 已禁用：按顺序处理

    try:
        for round_num in range(1, retry_rounds + 1):
            if not current_indices:
                print(f"\n第 {round_num} 轮: 无待查询数据")
                break

            print(f"\n{'='*60}")
            print(f"第 {round_num} 轮查询开始")
            print(f"待查询行数: {len(current_indices)}")
            print(f"{'='*60}\n")

            round_success = 0
            round_failed = 0
            failed_indices = []

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
                                    # 记录失败信息
                                    row = df.loc[idx]
                                    failed_records.append({
                                        'index': idx,
                                        'ENTNAME': _safe_str(row.get('ENTNAME', '')),
                                        '省份': _safe_str(row.get('省份', '')),
                                        '地区': _safe_str(row.get('地区', '')),
                                        'error': used_addr,
                                    })

                                # 定期保存
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
            print(f"  总成功率: {total_success}/{total_processed} ({total_success*100//total_processed if total_processed else 0}%)")

            # 准备下一轮
            if round_num < retry_rounds and failed_indices:
                print(f"\n准备第 {round_num + 1} 轮重试，剩余 {len(failed_indices)} 行")
                wait_time = min(10 * round_num, 30)
                print(f"等待 {wait_time} 秒...")
                time.sleep(wait_time)
                current_indices = failed_indices
                # 保持顺序处理
                # random.shuffle(current_indices)  # 已禁用：按顺序处理
            else:
                break

        # 保存最终结果
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
        # 确保无论如何都保存结果
        if not results_saved and not interrupted:
            print("\n\n确保保存结果...")
            try:
                save_final_results()
            except Exception as e:
                print(f"保存结果时出错: {e}")

    # 统计最终结果
    final_success = int((df[lng_col].notna() & df[lat_col].notna()).sum())
    final_missing = len(df) - final_success

    print(f"\n{'='*60}")
    print("最终统计:")
    print(f"  总行数: {len(df)}")
    print(f"  有坐标: {final_success} ({final_success*100//len(df)}%)")                  
    print(f"  无坐标: {final_missing} ({final_missing*100//len(df)}%)")
    print(f"{'='*60}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
