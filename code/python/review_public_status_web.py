from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT = Path(r"D:\Hospital_Pharmacy program")
CLASSIFICATION_DIR = ROOT / "data" / "hospital" / "hosp_panel" / "hosp_classification"
FINAL_CLEAN_PATH = CLASSIFICATION_DIR / "hosp_real_final_clean.csv"
CACHE_PATH = CLASSIFICATION_DIR / "hosp_real_public_review_web_cache.csv"

REVIEW_VALUE = "待复核"
PUBLIC_VALUE = "公立"
PRIVATE_VALUE = "民营"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
}

PUBLIC_REVIEW_COLS = [
    "public_original_before_web_review",
    "public_review_status",
    "public_review_result",
    "public_review_confidence",
    "public_review_basis",
    "public_review_search_status",
    "public_review_search_error",
    "public_review_source_title_1",
    "public_review_source_url_1",
    "public_review_source_snippet_1",
    "public_review_source_title_2",
    "public_review_source_url_2",
    "public_review_source_snippet_2",
    "public_review_source_title_3",
    "public_review_source_url_3",
    "public_review_source_snippet_3",
]


def read_csv_auto(path: Path, **kwargs) -> tuple[pd.DataFrame, str]:
    last_error: Exception | None = None
    for encoding in ["utf-8-sig", "utf-8", "gb18030", "gbk"]:
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs), encoding
        except Exception as exc:  # noqa: BLE001 - try common Chinese CSV encodings.
            last_error = exc
    raise RuntimeError(f"Cannot read {path}") from last_error


def clean_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def normalize_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().replace({"nan": "", "None": "", "<NA>": ""})


def parse_so_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    if "请输入验证码" in page_text or "访问过于频繁" in page_text or "SourceVerifyCode" in page_text:
        return []

    results: list[dict[str, str]] = []
    seen = set()
    for item in soup.select("li.res-list"):
        title_node = item.select_one("h3.res-title, h3")
        title = clean_text(title_node.get_text(" ", strip=True) if title_node else "")
        if not title or title in seen:
            continue
        link = title_node.find("a", href=True) if title_node else item.find("a", href=True)
        url = clean_text(link["href"]) if link else ""
        snippet = clean_text(item.get_text(" ", strip=True))
        results.append({"title": title, "url": url, "snippet": snippet[:900]})
        seen.add(title)
        if len(results) >= max_results:
            break
    return results


def parse_tianyancha_results(html: str, entname: str, max_results: int = 3) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(soup.get_text(" ", strip=True))
    if not text or "扫码登录" in text and entname not in text:
        return []
    short_name = re.sub(r"(有限公司|有限责任公司|股份有限公司|医院有限公司)$", "", entname)
    terms = [term for term in [entname, short_name] if len(term) >= 4]
    results: list[dict[str, str]] = []
    seen = set()
    for term in terms:
        for match in re.finditer(re.escape(term), text):
            # Skip the document title and filter/header area; result cards appear later.
            if match.start() < 1000:
                continue
            start = max(0, match.start() - 180)
            end = min(len(text), match.end() + 850)
            snippet = text[start:end]
            if snippet in seen:
                continue
            seen.add(snippet)
            results.append(
                {
                    "title": f"天眼查搜索结果：{entname}",
                    "url": f"https://www.tianyancha.com/search?key={entname}",
                    "snippet": snippet,
                }
            )
            if len(results) >= max_results:
                return results
    return results


def tianyancha_search(entname: str, timeout: int = 18) -> tuple[str, list[dict[str, str]], str]:
    try:
        response = requests.get(
            "https://www.tianyancha.com/search",
            params={"key": entname},
            headers=HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        results = parse_tianyancha_results(response.text, entname)
        return "ok" if results else "no_result", results, ""
    except Exception as exc:  # noqa: BLE001
        return "error", [], repr(exc)


def so_search(query: str, timeout: int = 18) -> tuple[str, list[dict[str, str]], str]:
    try:
        response = requests.get("https://www.so.com/s", params={"q": query}, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        results = parse_so_results(response.text)
        if not results and ("验证码" in response.text or "访问过于频繁" in response.text):
            return "blocked_captcha", [], "360 search verify page"
        return "ok", results, ""
    except Exception as exc:  # noqa: BLE001 - cache the exact failure for audit/resume.
        return "error", [], repr(exc)


def web_search(entname: str, query: str, timeout: int = 18) -> tuple[str, list[dict[str, str]], str]:
    tyc_status, tyc_results, tyc_error = tianyancha_search(entname, timeout=timeout)
    if tyc_results:
        return f"tianyancha_{tyc_status}", tyc_results, tyc_error
    so_status, so_results, so_error = so_search(query, timeout=timeout)
    if so_results:
        return f"so360_{so_status}", so_results, so_error
    return f"tianyancha_{tyc_status};so360_{so_status}", [], tyc_error or so_error


def load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    cache_df = pd.read_csv(CACHE_PATH, dtype=str, encoding="utf-8-sig").fillna("")
    cache: dict[str, dict] = {}
    for row in cache_df.to_dict("records"):
        try:
            row["results"] = json.loads(row.get("results_json", "[]") or "[]")
        except json.JSONDecodeError:
            row["results"] = []
        cache[str(row["companyid"])] = row
    return cache


def save_cache(cache: dict[str, dict]) -> None:
    rows = []
    for row in cache.values():
        rows.append(
            {
                "companyid": row.get("companyid", ""),
                "ENTNAME": row.get("ENTNAME", ""),
                "query": row.get("query", ""),
                "search_status": row.get("search_status", ""),
                "search_error": row.get("search_error", ""),
                "results_json": json.dumps(row.get("results", []), ensure_ascii=False),
            }
        )
    pd.DataFrame(rows).to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")


def relevant_web_text(entname: str, results: list[dict[str, str]]) -> str:
    short_name = re.sub(r"(有限公司|有限责任公司|股份有限公司|医院有限公司)$", "", entname)
    texts = []
    for result in results:
        combined = f"{result.get('title', '')} {result.get('snippet', '')}"
        if entname and entname in combined:
            texts.append(combined)
        elif short_name and len(short_name) >= 4 and short_name in combined:
            texts.append(combined)
        elif any(site in combined for site in ["企查查", "爱企查", "天眼查", "医院简介", "医院主页"]):
            texts.append(combined)
    return "\n".join(texts)


def score_public_private(row: pd.Series, results: list[dict[str, str]]) -> dict[str, str]:
    entname = clean_text(row.get("ENTNAME"))
    scope = clean_text(row.get("经营范围"))
    address = clean_text(row.get("注册地址"))
    web_text = relevant_web_text(entname, results)
    all_text = "\n".join([entname, scope, address, web_text])

    public_score = 0
    private_score = 0
    public_hits: list[str] = []
    private_hits: list[str] = []

    private_patterns = [
        ("民办非企业单位", 10),
        ("非政府办", 10),
        ("非公立", 10),
        ("民营医院", 9),
        ("民办医院", 9),
        ("私立医院", 9),
        ("社会办医", 8),
        ("社会组织类型", 5),
        ("有限公司", 8),
        ("有限责任公司", 8),
        ("个人独资", 8),
        ("全国诚信民营医院", 8),
        ("最具价值民营医院", 8),
    ]
    public_patterns = [
        ("公立医院", 10),
        ("公办", 9),
        ("政府办", 9),
        ("事业单位", 9),
        ("事业编制", 8),
        ("财政补助", 7),
        ("全民所有制", 7),
        ("国有", 6),
        ("公立", 8),
        ("三级甲等", 5),
        ("二级甲等", 4),
        ("开办资金", 3),
    ]

    for pattern, weight in private_patterns:
        if pattern in all_text:
            private_score += weight
            private_hits.append(pattern)
    for pattern, weight in public_patterns:
        if pattern in all_text:
            public_score += weight
            public_hits.append(pattern)

    private_name_patterns = [
        "庄稼医院",
        "禽病医院",
        "棉花医院",
        "医药门市部",
        "药膳营养部",
        "女子医院",
        "妇科医院",
        "男科医院",
        "美容",
        "整形",
        "仁爱",
        "友好",
        "京津",
        "中圣堂",
        "光明医院",
    ]
    public_name_patterns = [
        "人民医院",
        "县医院",
        "中心医院",
        "总医院",
        "职工医院",
        "卫生院",
        "妇幼保健",
        "红十字会医院",
        "红会医院",
        "医科大学",
        "大学附属医院",
        "学院附属医院",
        "铁路中心医院",
        "林业总医院",
        "矿务局总医院",
        "农场职工医院",
        "局职工医院",
        "自治区人民医院",
    ]
    for pattern in private_name_patterns:
        if pattern in entname:
            private_score += 5
            private_hits.append(f"name:{pattern}")
    for pattern in public_name_patterns:
        if pattern in entname:
            public_score += 6
            public_hits.append(f"name:{pattern}")

    if "有限公司" in entname or "有限责任公司" in entname:
        private_score += 10
        private_hits.append("name:有限公司")

    # Agricultural/veterinary metaphorical "hospital" entries are not public medical hospitals.
    if any(pattern in entname or pattern in scope for pattern in ["庄稼医院", "禽病", "农药", "化肥", "畜禽"]):
        private_score += 12
        private_hits.append("non_human_or_agricultural_hospital")

    result = ""
    status = "manual_review_unresolved"
    confidence = "low"
    if public_score >= private_score + 3 and public_score >= 6:
        result = PUBLIC_VALUE
        status = "classified_public"
        confidence = "high" if public_score >= 12 and public_score >= private_score + 6 else "medium"
    elif private_score >= public_score + 3 and private_score >= 6:
        result = PRIVATE_VALUE
        status = "classified_private"
        confidence = "high" if private_score >= 12 and private_score >= public_score + 6 else "medium"
    elif private_score > public_score:
        result = PRIVATE_VALUE
        status = "classified_private_low_confidence"
        confidence = "low"
    elif public_score > private_score:
        result = PUBLIC_VALUE
        status = "classified_public_low_confidence"
        confidence = "low"
    else:
        result = PRIVATE_VALUE
        status = "default_private_insufficient_evidence"
        confidence = "low"

    basis = (
        f"public_score={public_score} hits={public_hits}; "
        f"private_score={private_score} hits={private_hits}; "
        f"web_text_used={'yes' if web_text else 'no'}"
    )
    return {
        "public_review_result": result,
        "public_review_status": status,
        "public_review_confidence": confidence,
        "public_review_basis": basis,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-interval", type=float, default=0.8)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    df, input_encoding = read_csv_auto(FINAL_CLEAN_PATH, dtype=str, low_memory=False)
    df = df.fillna("")
    df["companyid"] = normalize_series(df["companyid"])
    df["public"] = normalize_series(df["public"])

    if "public_original_before_web_review" not in df.columns:
        df["public_original_before_web_review"] = df["public"]

    for col in PUBLIC_REVIEW_COLS:
        if col not in df.columns:
            df[col] = ""

    targets = df[df["public"].eq(REVIEW_VALUE) | df["public_original_before_web_review"].eq(REVIEW_VALUE)].copy()
    if args.limit:
        targets = targets.head(args.limit).copy()

    cache = {} if args.refresh else load_cache()
    last_request_ts = 0.0
    processed = 0

    for idx, row in targets.iterrows():
        companyid = clean_text(row["companyid"])
        entname = clean_text(row["ENTNAME"])
        query = f"{entname} 企查查 爱企查 公立 民营 医院性质"
        if companyid not in cache:
            wait = args.min_interval - (time.time() - last_request_ts)
            if wait > 0:
                time.sleep(wait)
            status, results, error = web_search(entname, query)
            last_request_ts = time.time()
            cache[companyid] = {
                "companyid": companyid,
                "ENTNAME": entname,
                "query": query,
                "search_status": status,
                "search_error": error,
                "results": results,
            }
            save_cache(cache)

        cached = cache[companyid]
        results = cached.get("results", [])
        decision = score_public_private(row, results)
        df.at[idx, "public"] = decision["public_review_result"]
        df.at[idx, "public_review_status"] = decision["public_review_status"]
        df.at[idx, "public_review_result"] = decision["public_review_result"]
        df.at[idx, "public_review_confidence"] = decision["public_review_confidence"]
        df.at[idx, "public_review_basis"] = decision["public_review_basis"]
        df.at[idx, "public_review_search_status"] = cached.get("search_status", "")
        df.at[idx, "public_review_search_error"] = cached.get("search_error", "")
        for n in range(3):
            result = results[n] if n < len(results) else {}
            df.at[idx, f"public_review_source_title_{n + 1}"] = result.get("title", "")
            df.at[idx, f"public_review_source_url_{n + 1}"] = result.get("url", "")
            df.at[idx, f"public_review_source_snippet_{n + 1}"] = result.get("snippet", "")

        processed += 1
        if processed % 25 == 0 or processed == len(targets):
            print(f"processed {processed}/{len(targets)}")

    df.to_csv(FINAL_CLEAN_PATH, index=False, encoding="utf-8-sig")

    print("public review summary")
    print(f"input encoding: {input_encoding}")
    print(f"targets: {len(targets):,}")
    print("\npublic counts:")
    print(df["public"].value_counts(dropna=False).to_string())
    reviewed = df[df["public_original_before_web_review"].eq(REVIEW_VALUE)]
    print("\nreview result:")
    print(reviewed["public_review_result"].value_counts(dropna=False).to_string())
    print("\nreview status:")
    print(reviewed["public_review_status"].value_counts(dropna=False).to_string())
    print("\nreview confidence:")
    print(reviewed["public_review_confidence"].value_counts(dropna=False).to_string())
    print(f"\nUpdated: {FINAL_CLEAN_PATH}")
    print(f"Cache: {CACHE_PATH}")


if __name__ == "__main__":
    main()
