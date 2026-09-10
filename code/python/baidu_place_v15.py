"""
百度 Place API 补全医院坐标（稳定限流预警版）

功能：
1. 成功缓存（place_cache.csv）
2. 失败缓存（place_failed_cache.csv，含失败原因）
3. limit 仅作用于缺失坐标的前 N 条
4. 默认单线程，防止百度 API 限流
5. 并发 / 配额受限自动统计并预警
6. 新增地区清洗：自动修正"全国市"为"全国"，保留合法地区值
7. 新增日志功能：记录所有API请求URL和完整返回数据到日志文件
"""

import csv
import threading
import argparse
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import requests
import pandas as pd
import time

# ===================== 默认路径与日志配置 =====================
DEFAULT_OL_DATA_DIR = Path(r"D:\Hospital_Pharmacy program\data\hospital\hosp_registered_data\ol_data")
DEFAULT_OL_DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = str(DEFAULT_OL_DATA_DIR / "place_api_query_log.jsonl")

def setup_logger():
    """配置日志记录器，记录API请求和响应到文件"""
    logger = logging.getLogger("api_logger")
    logger.setLevel(logging.INFO)
    
    # 避免重复添加handler
    if not logger.handlers:
        # 文件handler - 记录到JSONL文件
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        
        # 简单格式，因为我们会写入JSON
        formatter = logging.Formatter('%(message)s')
        file_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
    
    return logger

# 初始化日志记录器
api_logger = setup_logger()

def log_api_request(query, region, url, params, response_status, response_text, result_summary=None):
    """
    记录API请求和响应到日志文件
    
    Args:
        query: 查询关键字
        region: 查询地区
        url: 请求URL
        params: 请求参数
        response_status: HTTP状态码
        response_text: 响应原始文本
        result_summary: 结果摘要（可选）
    """
    log_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "query": query,
        "region": region,
        "request": {
            "url": url,
            "params": {k: v for k, v in params.items() if k != "ak"},  # 隐藏AK
            "ak_masked": params.get("ak", "")[:8] + "****" if params.get("ak") else ""
        },
        "response": {
            "http_status": response_status,
            "body": None,
            "raw_text_length": len(response_text) if response_text else 0
        },
        "result_summary": result_summary
    }
    
    # 尝试解析响应JSON
    try:
        log_entry["response"]["body"] = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        log_entry["response"]["body"] = response_text[:500] if response_text else None
    
    # 写入日志
    api_logger.info(json.dumps(log_entry, ensure_ascii=False))

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it=None, **kwargs):
        return it or []

# ===================== 百度 AK =====================
API_KEYS = [
    "BgYCfuoQlkyAKj6jGLzXYHQPpr8Fcb2M",
    # "3NmRY0IL3O8zPaoN2agfBEPvVwmPOFaZ",
    # "DpAzhY1zVy3TUgvzAT7nfhUwCrVdSXIg",

    # "7oKWYQJuyIY1hQIA53pJZVSspYM2BG72",
    # "x0rNo9aWl4tw5qOv7aGBKnDf63gE4Owb",
    # "cHAOhSdYCfVx5i8c150m2PACRuufKZQU",

    # "2UQC7HSNJOF8",
]

# ===================== 工具函数 =====================
def _safe_str(x):
    return "" if x is None or pd.isna(x) else str(x).strip()

def read_csv_with_fallback(path: Path):
    for enc in ["utf-8-sig", "utf-8", "gb18030", "gbk", "cp936", "latin-1"]:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except Exception:
            pass
    raise RuntimeError(f"无法读取文件: {path}")

def clean_hospital_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r"[（(].*?[)）]", "", name)
    name = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", name)
    return name.strip()

def clean_region(region: str) -> str:
    """
    清洗地区值，修正异常值并保留合法格式
    - 核心：将"全国市"修正为"全国"
    - 过滤特殊字符，保留合法行政区划名称
    """
    if not region:
        return ""
    # 修正错误值：全国市 → 全国
    region = region.replace("全国市", "全国")
    # 过滤非合法字符（仅保留中文、字母、数字）
    region = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", region).strip()
    # 兜底：清洗后为空则返回空字符串
    return region if region else ""

# ===================== 成功缓存 =====================
def load_cache(path: Path):
    if not path.exists():
        return {}
    df = read_csv_with_fallback(path)
    cache = {}
    for _, r in df.iterrows():
        cache[(_safe_str(r["ENTNAME"]), _safe_str(r["地区"]))] = (
            r["lng"], r["lat"]
        )
    print(f"成功缓存加载完成：{len(cache)} 条")
    return cache

def append_cache(path, ent, region, lng, lat, lock):
    with lock:
        has_header = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if not has_header:
                w.writerow(["ENTNAME", "地区", "lng", "lat"])
            w.writerow([ent, region, lng or "", lat or ""])

# ===================== 失败缓存 =====================
def load_failed_cache(path: Path):
    if not path.exists():
        return set()
    df = read_csv_with_fallback(path)
    failed = set(
        (_safe_str(r["ENTNAME"]), _safe_str(r["地区"]))
        for _, r in df.iterrows()
    )
    print(f"失败缓存加载完成：{len(failed)} 条")
    return failed

def append_failed_cache(path, ent, region, err_type, err_detail, lock):
    with lock:
        has_header = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if not has_header:
                w.writerow(
                    ["ENTNAME", "地区", "失败原因", "错误详情", "记录时间"]
                )
            w.writerow([
                ent,
                region,
                err_type,
                err_detail,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ])

# ===================== 百度 Place API =====================
# 302错误重试次数上限
MAX_302_RETRIES = 3

def query_place(ent, region, ak, use_strict=True, include_tags=True, get_details=False):
    """
    查询百度地图 Place API

    Args:
        ent: 查询关键字（地点名称）
        region: 检索行政区划区域
        ak: 开发者密钥
        use_strict: 是否严格限制区域内（city_limit=true）
        include_tags: 是否使用医疗标签过滤
        get_details: 是否获取详细信息（scope=2）

    Returns:
        (lng, lat, err_type, err_detail, best_result)
        当err_type为"配额超限_跳过"时，表示连续3次302错误，调用方应跳过该记录
    """
    url = "https://api.map.baidu.com/place/v2/search"
    city_limit = use_strict and clean_region(region) != "全国"
    params = {
        "query": ent,
        "region": region,
        "output": "json",
        "ak": ak,
        "city_limit": "true" if city_limit else "false",  # 全国检索时不限制城市
        "scope": 2 if get_details else 1,  # 1=基本信息，2=详细信息
    }

    # 医疗设施相关标签
    if include_tags and ("医院" in ent or "医" in ent):
        params["tag"] = "医疗"

    # 302错误重试计数
    retry_302_count = 0

    while retry_302_count < MAX_302_RETRIES:
        try:
            time.sleep(1)
            response = requests.get(url, params=params, timeout=10)

            # 打印详细的请求和响应信息
            print(f"\n{'='*60}")
            print(f"API 请求详情:")
            print(f"  URL: {url}")
            print(f"  参数: {params}")
            print(f"  HTTP状态码: {response.status_code}")
            print(f"  响应内容: {response.text}")
            print(f"{'='*60}\n")

            r = response.json()
            status = r.get("status")

            if status == 0:
                if r.get("results"):
                    # 获取所有结果并进行评分匹配
                    results = r["results"]
                    best_result = _score_and_select_result(ent, results)

                    if best_result:
                        loc = best_result["location"]
                        # 记录成功日志
                        log_api_request(
                            query=ent,
                            region=region,
                            url=url,
                            params=params,
                            response_status=response.status_code,
                            response_text=response.text,
                            result_summary={
                                "status": "success",
                                "matched_name": best_result.get("name"),
                                "lng": loc["lng"],
                                "lat": loc["lat"],
                                "total_results": len(results)
                            }
                        )
                        return loc["lng"], loc["lat"], None, None, best_result
                    else:
                        # 记录无匹配结果日志
                        log_api_request(
                            query=ent,
                            region=region,
                            url=url,
                            params=params,
                            response_status=response.status_code,
                            response_text=response.text,
                            result_summary={
                                "status": "no_match",
                                "error": "虽有结果但无最佳匹配",
                                "total_results": len(results)
                            }
                        )
                        return None, None, "查询无匹配结果", "虽有结果但无最佳匹配", None
                else:
                    # 记录无结果日志
                    log_api_request(
                        query=ent,
                        region=region,
                        url=url,
                        params=params,
                        response_status=response.status_code,
                        response_text=response.text,
                        result_summary={
                            "status": "no_results",
                            "error": "status=0 但无 results"
                        }
                    )
                    return None, None, "查询无结果", "status=0 但无 results", None
            
            elif status == 302:
                # 配额超限，增加重试计数
                retry_302_count += 1
                print(f"⚠️ 天配额超限(302)，第{retry_302_count}次重试 | 记录: {ent}")
                
                # 如果达到重试上限，返回特殊标记让调用方跳过
                if retry_302_count >= MAX_302_RETRIES:
                    print(f"⏭️ 记录 [{ent}] 连续{retry_302_count}次配额超限(302)，跳过该记录")
                    log_api_request(
                        query=ent,
                        region=region,
                        url=url,
                        params=params,
                        response_status=response.status_code,
                        response_text=response.text,
                        result_summary={
                            "status": "quota_exceeded_skip",
                            "error": f"连续{retry_302_count}次配额超限，跳过该记录",
                            "api_status": status
                        }
                    )
                    return None, None, "配额超限_跳过", f"连续{retry_302_count}次配额超限，跳过该记录", None
                
                # 等待后重试
                time.sleep(2)
                continue  # 继续while循环重试
            
            else:
                # 其他错误状态码
                status_map = {
                    2: "请求参数错误",
                    3: "权限校验失败",
                    4: "AK 不存在或非法",
                    5: "百度服务异常",
                    6: "请求频率过高",
                    101: "API_KEY 无效",
                    302: "配额超限",
                    401: "并发或QPS受限",
                    402: "并发或QPS受限",
                    403: "并发或QPS受限",
                }

                # 记录API错误日志
                err_msg = status_map.get(status, "未知错误")
                log_api_request(
                    query=ent,
                    region=region,
                    url=url,
                    params=params,
                    response_status=response.status_code,
                    response_text=response.text,
                    result_summary={
                        "status": "api_error",
                        "error_type": err_msg,
                        "api_status": status
                    }
                )
                return None, None, err_msg, f"status={status}, 响应={response.text[:200]}", None

        except Exception as e:
            print(f"\n{'='*60}")
            print(f"API 请求异常:")
            print(f"  URL: {url}")
            print(f"  参数: {params}")
            print(f"  异常类型: {type(e).__name__}")
            print(f"  异常信息: {str(e)}")
            print(f"{'='*60}\n")
            
            # 记录异常日志
            log_api_request(
                query=ent,
                region=region,
                url=url,
                params=params,
                response_status=None,
                response_text=None,
                result_summary={
                    "status": "exception",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
            )
            return None, None, "网络异常", str(e), None
    
    # 理论上不会执行到这里，但作为兜底
    return None, None, "配额超限", "重试次数耗尽", None

# ===================== 结果评分和选择 =====================
def _score_and_select_result(ent, results, top_n=1):
    """
    对查询结果进行评分和匹配

    评分规则：
    1. 名称相似度（精确匹配权重最高）
    2. 结果排序位置
    3. 是否有详细信息
    """
    import difflib

    if not results:
        return None

    scored_results = []
    clean_ent = clean_hospital_name(ent)

    for idx, result in enumerate(results):
        name = result.get("name", "")
        clean_name = clean_hospital_name(name)

        # 计算相似度
        exact_match = name == ent or clean_name == clean_ent
        similarity = difflib.SequenceMatcher(None, clean_ent, clean_name).ratio()

        # 综合评分
        score = 0
        if exact_match:
            score += 100  # 精确匹配最高分
        score += similarity * 50  # 相似度占50分
        score += (10 - idx) * 5  # 靠前的结果加分（最多50分）

        # 有详细信息加分
        if result.get("detail_info"):
            score += 10

        scored_results.append((score, result))

    # 排序并返回最佳结果
    scored_results.sort(key=lambda x: x[0], reverse=True)
    return scored_results[0][1] if scored_results else None

# ===================== 构造候选地址 =====================
def build_candidates(row, include_structured=True):
    ent = _safe_str(row.get("ENTNAME"))
    # 清洗地区/省份值，修正"全国市"为"全国"
    area = clean_region(_safe_str(row.get("地区")))
    prov = clean_region(_safe_str(row.get("省份")))
    clean = clean_hospital_name(ent)

    candidates = [
        (ent, area),
        (clean, area),
        (ent, prov),
        (ent, ""),
        (clean, ""),
    ]

    # 如果有详细的地址信息，添加结构化地址候选
    if include_structured:
        address = _safe_str(row.get("地址"))
        if address and address != ent:
            candidates.insert(0, (address, area))

    return list(dict.fromkeys([c for c in candidates if c[0]]))

# ===================== 单行处理 =====================
def process_row(
    idx,
    df,
    cache,
    failed_cache,
    cache_path,
    failed_cache_path,
    lock,
    stats,
    config=None
):
    if config is None:
        config = {"use_structured": False, "use_tags": True, "strict_region": True}

    last_err = ("未知错误", "未成功完成 API 请求")

    if pd.notna(df.at[idx, "百度经度"]) and pd.notna(df.at[idx, "百度纬度"]):
        with lock:
            stats["跳过_已有坐标"] += 1
        return

    row = df.loc[idx]

    for ent, region in build_candidates(row, include_structured=config.get("use_structured", False)):
        
        if region is None or region == "":
            # 如果没有地区信息，就跳过
            region = "全国"

        if (ent, region) in failed_cache:
            last_err = ("历史失败缓存", "该地址此前多次失败，已跳过")
            with lock:
                stats["跳过_失败缓存"] += 1
            continue

        if (ent, region) in cache:
            lng, lat = cache[(ent, region)]
            if pd.notna(lng) and pd.notna(lat):
                df.at[idx, "百度经度"] = lng
                df.at[idx, "百度纬度"] = lat
                with lock:
                    stats["成功"] += 1
                return

        for ak in API_KEYS:
            # 尝试多种查询策略：先严格查询，后宽松查询
            for use_strict in [True, False]:
                for get_details in [True, False]:
                    lng, lat, err_type, err_detail, result = query_place(
                        ent, region, ak,
                        use_strict=use_strict and config.get("strict_region", True),
                        include_tags=config.get("use_tags", True),
                        get_details=get_details
                    )
                    if lng is not None:
                        df.at[idx, "百度经度"] = lng
                        df.at[idx, "百度纬度"] = lat
                        cache[(ent, region)] = (lng, lat)
                        append_cache(cache_path, ent, region, lng, lat, lock)
                        with lock:
                            stats["成功"] += 1
                            stats[f"策略_严格{use_strict}_详细{get_details}"] = stats.get(f"策略_严格{use_strict}_详细{get_details}", 0) + 1
                        return
                    else:
                        last_err = (err_type, err_detail)
                        
                        # 如果是"配额超限_跳过"，直接跳过该记录（不写入失败缓存）
                        if err_type == "配额超限_跳过":
                            with lock:
                                stats["跳过_配额超限"] = stats.get("跳过_配额超限", 0) + 1
                            return  # 直接返回，不写入失败缓存
                        
                        if err_type in ["并发或QPS受限", "请求频率过高", "配额超限", "API_KEY 无效"]:
                            with lock:
                                stats["并发或配额受限"] += 1

    ent, region = build_candidates(row, include_structured=config.get("use_structured", False))[0]
    failed_cache.add((ent, region))
    append_failed_cache(
        failed_cache_path, ent, region, last_err[0], last_err[1], lock
    )
    with lock:
        stats["失败"] += 1

# ===================== 主函数 =====================
def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="百度 Place API 补全医院坐标（增强版）")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制处理的缺失坐标行数；0 表示处理全部（默认）")
    parser.add_argument("--workers", type=int, default=1,
                        help="并发线程数（默认1，防止API限流）")
    parser.add_argument("--input", type=str, default=str(DEFAULT_OL_DATA_DIR / "05_added_hospital_baidu_place_api_input.csv"),
                        help="输入文件路径")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OL_DATA_DIR / "06_added_hospital_baidu_place_result.csv"),
                        help="输出文件路径")
    parser.add_argument("--use-structured", action="store_true", default=True,
                        help="使用结构化地址进行查询（如果有地址列）")
    parser.add_argument("--no-tags", action="store_true", default=False,
                        help="禁用医疗标签过滤")
    parser.add_argument("--strict-region", action="store_true", default=True,
                        help="严格限制检索区域内（默认开启）")
    parser.add_argument("--no-strict-region", action="store_false", dest="strict_region",
                        help="禁用严格区域限制")
    args = parser.parse_args()
    
    # 配置参数
    input_file = args.input
    output_file = args.output
    limit = args.limit
    workers = args.workers
    cache_file = str(DEFAULT_OL_DATA_DIR / "place_cache.csv")
    failed_cache_file = str(DEFAULT_OL_DATA_DIR / "place_failed_cache.csv")

    # 功能配置
    config = {
        "use_structured": args.use_structured,
        "use_tags": not args.no_tags,
        "strict_region": args.strict_region,
    }

    print(f"配置参数:")
    print(f"  输入文件: {input_file}")
    print(f"  输出文件: {output_file}")
    print(f"  处理限制: {limit if limit else '无限制'}")
    print(f"  并发线程: {workers}")
    print(f"  结构化地址: {'启用' if config['use_structured'] else '禁用'}")
    print(f"  医疗标签过滤: {'启用' if config['use_tags'] else '禁用'}")
    print(f"  严格区域限制: {'启用' if config['strict_region'] else '禁用'}")
    print(f"  API日志文件: {LOG_FILE}")
    print()

    df = read_csv_with_fallback(Path(input_file))
    for c in ["百度经度", "百度纬度"]:
        if c not in df.columns:
            df[c] = pd.NA

    # The default input is the handoff file produced after reverse-geocode
    # matching. Rows in that file should be queried by Place API even if they
    # still carry old Baidu geocode coordinates from the earlier step.
    force_mask = pd.Series(False, index=df.index)
    if "needs_place_api" in df.columns:
        force_mask = force_mask | pd.to_numeric(df["needs_place_api"], errors="coerce").fillna(0).eq(1)
    if "place_reason" in df.columns:
        force_mask = force_mask | df["place_reason"].astype(str).str.strip().ne("")
    if force_mask.any():
        for c in ["百度经度", "百度纬度"]:
            backup_col = f"原{c}_place前"
            if backup_col not in df.columns:
                df[backup_col] = df[c]
            df.loc[force_mask, c] = pd.NA

    cache = load_cache(Path(cache_file))
    failed_cache = load_failed_cache(Path(failed_cache_file))

    need_idx = df.index[df["百度经度"].isna() | df["百度纬度"].isna()].tolist()
    if limit:
        need_idx = need_idx[:limit]

    stats = {
        "成功": 0,
        "失败": 0,
        "跳过_已有坐标": 0,
        "跳过_失败缓存": 0,
        "并发或配额受限": 0,
    }

    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(tqdm(
            ex.map(
                lambda i: process_row(
                    i, df, cache, failed_cache,
                    Path(cache_file), Path(failed_cache_file),
                    lock, stats, config
                ),
                need_idx
            ),
            total=len(need_idx),
            desc="百度坐标查询"
        ))

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 60)
    print("本轮运行统计")

    # 分类显示统计信息
    basic_stats = {
        "成功": stats.get("成功", 0),
        "失败": stats.get("失败", 0),
        "跳过_已有坐标": stats.get("跳过_已有坐标", 0),
        "跳过_失败缓存": stats.get("跳过_失败缓存", 0),
        "跳过_配额超限": stats.get("跳过_配额超限", 0),
        "并发或配额受限": stats.get("并发或配额受限", 0),
    }

    print("基础统计：")
    for k, v in basic_stats.items():
        print(f"  {k}: {v}")

    # 显示策略统计（如果有的话）
    strategy_stats = {k: v for k, v in stats.items() if k.startswith("策略_")}
    if strategy_stats:
        print("\n查询策略统计：")
        for k, v in strategy_stats.items():
            print(f"  {k}: {v}")

    print("-" * 60)
    print(f"总行数: {len(df)}")
    print(f"已有坐标: {df['百度经度'].notna().sum()}")
    print(f"仍缺失坐标: {df['百度经度'].isna().sum()}")

    success_rate = (df['百度经度'].notna().sum() / len(df) * 100) if len(df) > 0 else 0
    print(f"坐标完成率: {success_rate:.1f}%")

    print("\n运行环境诊断")
    if stats["并发或配额受限"] > 0:
        print(f"检测到 {stats['并发或配额受限']} 次 API 限流或配额受限")
        print("建议：使用 --workers 1，并等待一段时间后重跑")
    else:
        print("未检测到明显的 API 限流问题")

    print("\n查询功能说明")
    print("✓ city_limit: 严格限制区域内检索（全国地区自动关闭）")
    print("✓ tag: 医疗标签过滤")
    print("✓ scope: 获取详细POI信息")
    print("✓ 多结果评分: 根据名称相似度、排序位置等综合评分")
    print("✓ 地区清洗: 自动修正'全国市'为'全国'，过滤非法字符")
    print("✓ API日志: 记录所有请求URL和完整返回数据到JSONL文件")

    print("=" * 60)
    print(f"结果文件已保存: {output_file}")
    print(f"API日志文件已保存: {LOG_FILE}")

if __name__ == "__main__":
    main()
