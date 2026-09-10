from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT = Path(r"D:\Hospital_Pharmacy program")
CLASSIFICATION_DIR = ROOT / "data" / "hospital" / "hosp_panel" / "hosp_classification"
INPUT_PATH = CLASSIFICATION_DIR / "hosp_real_final_clean.csv"
DETAIL_OUTPUT_PATH = CLASSIFICATION_DIR / "hosp_real_province_diff_review.csv"
FULL_OUTPUT_PATH = CLASSIFICATION_DIR / "hosp_real_final_clean_province_reviewed.csv"
CACHE_PATH = CLASSIFICATION_DIR / "hosp_real_province_diff_web_cache.csv"
OVERRIDE_PATH = CLASSIFICATION_DIR / "hosp_real_province_diff_manual_overrides.csv"

REGISTERED_ADDRESS_COL = "\u6ce8\u518c\u5730\u5740"

PROVINCES = [
    "北京市",
    "天津市",
    "河北省",
    "山西省",
    "内蒙古自治区",
    "辽宁省",
    "吉林省",
    "黑龙江省",
    "上海市",
    "江苏省",
    "浙江省",
    "安徽省",
    "福建省",
    "江西省",
    "山东省",
    "河南省",
    "湖北省",
    "湖南省",
    "广东省",
    "广西壮族自治区",
    "海南省",
    "重庆市",
    "四川省",
    "贵州省",
    "云南省",
    "西藏自治区",
    "陕西省",
    "甘肃省",
    "青海省",
    "宁夏回族自治区",
    "新疆维吾尔自治区",
]

DIRECT_MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}
ROAD_SUFFIX_PATTERN = r"(路|街|大道|大街|街道|巷|弄|里|桥|段|号|镇|村)"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
}

QUERY_SUFFIX = "\u5730\u5740 \u5b98\u7f51 \u7b80\u4ecb"


def clean_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def strip_admin_suffix(name: str) -> list[str]:
    name = clean_text(name)
    if not name:
        return []
    variants = {name}
    suffixes = [
        "维吾尔自治区",
        "壮族自治区",
        "回族自治区",
        "自治区",
        "自治州",
        "地区",
        "盟",
        "省",
        "市",
        "县",
        "区",
    ]
    for suffix in suffixes:
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            variants.add(name[: -len(suffix)])
    return sorted(variants, key=len, reverse=True)


def term_in_text(text: str, term: str, exact_name: str = "") -> bool:
    if not term or term not in text:
        return False
    # Avoid treating street names such as "重庆路" or "北京街" as province evidence.
    if exact_name in DIRECT_MUNICIPALITIES or term in {"北京", "天津", "上海", "重庆"}:
        if re.search(rf"{re.escape(term)}{ROAD_SUFFIX_PATTERN}", text):
            return False
    return True


def make_terms(province: str, city: str, county: str) -> list[tuple[str, int, str, str]]:
    terms: list[tuple[str, int, str]] = []
    province = clean_text(province)
    for term in strip_admin_suffix(province):
        weight = 4 if term == province else 2
        terms.append((term, weight, "province", province))
    for term in strip_admin_suffix(city):
        if term not in {"市辖", "县", "市辖区"}:
            terms.append((term, 3, "city", clean_text(city)))
    for term in strip_admin_suffix(county):
        if term not in {"辖区", "市辖区"}:
            terms.append((term, 3, "county", clean_text(county)))
    seen = set()
    out = []
    for term, weight, level, exact_name in terms:
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        out.append((term, weight, level, exact_name))
    return out


def score_candidate(texts: list[str], province: str, city: str, county: str) -> tuple[int, list[str]]:
    joined = "\n".join(clean_text(t) for t in texts if clean_text(t))
    score = 0
    hits: list[str] = []
    for term, weight, level, exact_name in make_terms(province, city, county):
        if term_in_text(joined, term, exact_name):
            score += weight
            hits.append(f"{level}:{term}")
    return score, hits


def detect_province_mentions(texts: list[str]) -> dict[str, int]:
    joined = "\n".join(clean_text(t) for t in texts if clean_text(t))
    scores: dict[str, int] = {}
    for province in PROVINCES:
        score = 0
        if province in joined:
            score += 5
        for variant in strip_admin_suffix(province):
            if variant == province:
                continue
            if term_in_text(joined, variant, province):
                score += 2
        if score:
            scores[province] = score
    return scores


def decode_sogou_url(url: str) -> str:
    url = clean_text(url)
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/link?") or url.startswith("link?"):
        qs = parse_qs(urlparse(url).query)
        for key in ("url", "query", "u"):
            if qs.get(key):
                return unquote(qs[key][0])
    return url


def decode_so_url(url: str) -> str:
    url = clean_text(url)
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.so.com" + url
    return url


def parse_so_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    if "请输入验证码" in page_text or "访问过于频繁" in page_text:
        return []

    results: list[dict[str, str]] = []
    seen_titles = set()
    for item in soup.select("li.res-list"):
        title_node = item.select_one("h3.res-title, h3")
        title = clean_text(title_node.get_text(" ", strip=True) if title_node else "")
        if not title or title in seen_titles:
            continue
        link = title_node.find("a", href=True) if title_node else item.find("a", href=True)
        url = decode_so_url(link["href"]) if link else ""
        snippet = clean_text(item.get_text(" ", strip=True))
        results.append({"title": title, "url": url, "snippet": snippet[:900]})
        seen_titles.add(title)
        if len(results) >= max_results:
            break

    if not results and page_text:
        results.append({"title": "so_page_text", "url": "", "snippet": page_text[:900]})
    return results


def parse_sogou_results(html: str, max_results: int = 5) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    if "SourceVerifyCode" in page_text or "访问时间" in page_text and "验证码" in page_text:
        return []
    results: list[dict[str, str]] = []
    seen_titles = set()

    for title_node in soup.select("h3.vr-title, h3.js_title, h3[class*=title], h4"):
        title = clean_text(title_node.get_text(" ", strip=True))
        if not title or title in seen_titles:
            continue
        parent = title_node.find_parent(["div", "section", "article"]) or title_node.parent
        snippet = clean_text(parent.get_text(" ", strip=True) if parent else title)
        link = title_node.find("a", href=True) or (parent.find("a", href=True) if parent else None)
        url = decode_sogou_url(link["href"]) if link else ""
        results.append({"title": title, "url": url, "snippet": snippet[:900]})
        seen_titles.add(title)
        if len(results) >= max_results:
            break

    if not results:
        text = clean_text(soup.get_text(" ", strip=True))
        if text:
            results.append({"title": "sogou_page_text", "url": "", "snippet": text[:900]})

    return results


def sogou_search(query: str, timeout: int = 20) -> tuple[str, list[dict[str, str]], str]:
    try:
        response = requests.get(
            "https://www.sogou.com/web",
            params={"query": query},
            headers=HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        results = parse_sogou_results(response.text)
        if not results and ("SourceVerifyCode" in response.text or "验证码" in response.text):
            return "blocked_captcha", [], "sogou source verify page"
        return "ok", results, ""
    except Exception as exc:  # noqa: BLE001 - cache the exact failure for audit/resume.
        return "error", [], repr(exc)


def so_search(query: str, timeout: int = 20) -> tuple[str, list[dict[str, str]], str]:
    try:
        response = requests.get(
            "https://www.so.com/s",
            params={"q": query},
            headers=HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        results = parse_so_results(response.text)
        if not results and ("验证码" in response.text or "访问过于频繁" in response.text):
            return "blocked_captcha", [], "360 search verify page"
        return "ok", results, ""
    except Exception as exc:  # noqa: BLE001 - cache the exact failure for audit/resume.
        return "error", [], repr(exc)


def web_search(query: str) -> tuple[str, str, list[dict[str, str]], str]:
    status, results, error = so_search(query)
    if status == "ok" and results:
        return "so360", status, results, error
    sogou_status, sogou_results, sogou_error = sogou_search(query)
    if sogou_status == "ok" and sogou_results:
        return "sogou", sogou_status, sogou_results, sogou_error
    return "so360+sogou", status if status != "ok" else sogou_status, results or sogou_results, error or sogou_error


def load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    cache_df = pd.read_csv(CACHE_PATH, dtype=str, encoding="utf-8-sig").fillna("")
    cache = {}
    for row in cache_df.to_dict("records"):
        try:
            row["results"] = json.loads(row.get("results_json", "[]") or "[]")
        except json.JSONDecodeError:
            row["results"] = []
        cache[str(row["companyid"])] = row
    return cache


def load_overrides() -> dict[str, dict[str, str]]:
    if not OVERRIDE_PATH.exists():
        return {}
    overrides = pd.read_csv(OVERRIDE_PATH, dtype=str, encoding="utf-8-sig").fillna("")
    return {str(row["companyid"]): row for row in overrides.to_dict("records")}


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
                "search_engine": row.get("search_engine", ""),
                "results_json": json.dumps(row.get("results", []), ensure_ascii=False),
            }
        )
    pd.DataFrame(rows).to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")


def choose_side(row: pd.Series, results: list[dict[str, str]]) -> dict[str, str]:
    local_texts = [
        clean_text(row.get("ENTNAME")),
        clean_text(row.get(REGISTERED_ADDRESS_COL)),
    ]
    web_texts = []
    for result in results:
        web_texts.extend([result.get("title", ""), result.get("snippet", "")])

    business_score, business_hits = score_candidate(
        local_texts + web_texts,
        row.get("business_province", ""),
        row.get("business_city", ""),
        row.get("business_county", ""),
    )
    spatial_score, spatial_hits = score_candidate(
        local_texts + web_texts,
        row.get("spatial_province", ""),
        row.get("spatial_city", ""),
        row.get("spatial_county", ""),
    )

    local_business_score, local_business_hits = score_candidate(
        local_texts,
        row.get("business_province", ""),
        row.get("business_city", ""),
        row.get("business_county", ""),
    )
    local_spatial_score, local_spatial_hits = score_candidate(
        local_texts,
        row.get("spatial_province", ""),
        row.get("spatial_city", ""),
        row.get("spatial_county", ""),
    )
    web_business_score, web_business_hits = score_candidate(
        web_texts,
        row.get("business_province", ""),
        row.get("business_city", ""),
        row.get("business_county", ""),
    )
    web_spatial_score, web_spatial_hits = score_candidate(
        web_texts,
        row.get("spatial_province", ""),
        row.get("spatial_city", ""),
        row.get("spatial_county", ""),
    )
    province_mentions = detect_province_mentions(local_texts + web_texts)
    top_other_province = ""
    top_other_score = 0
    for province, score in sorted(province_mentions.items(), key=lambda item: item[1], reverse=True):
        if province not in {clean_text(row.get("business_province")), clean_text(row.get("spatial_province"))}:
            top_other_province = province
            top_other_score = score
            break

    side = "manual_review"
    province = ""
    status = "needs_manual_review"
    confidence = "low"

    # Web evidence is preferred. Local name/address is used when search cannot
    # produce a decisive, auditable source.
    if top_other_province and top_other_score >= max(web_business_score, web_spatial_score, 0) + 2 and top_other_score >= 5:
        side = "other"
        province = top_other_province
        status = "confirmed_other_province_by_web_or_text"
        confidence = "high" if top_other_score >= 7 else "medium"
    elif web_business_score >= 4 and web_business_score >= web_spatial_score + 2:
        side = "business"
        province = clean_text(row.get("business_province"))
        status = "confirmed_by_web"
        confidence = "high" if web_business_score >= 6 else "medium"
    elif web_spatial_score >= 4 and web_spatial_score >= web_business_score + 2:
        side = "spatial"
        province = clean_text(row.get("spatial_province"))
        status = "confirmed_by_web"
        confidence = "high" if web_spatial_score >= 6 else "medium"
    elif local_business_score >= 3 and local_business_score >= local_spatial_score + 2:
        side = "business"
        province = clean_text(row.get("business_province"))
        status = "confirmed_by_name_or_registered_address"
        confidence = "medium"
    elif local_spatial_score >= 3 and local_spatial_score >= local_business_score + 2:
        side = "spatial"
        province = clean_text(row.get("spatial_province"))
        status = "confirmed_by_name_or_registered_address"
        confidence = "medium"

    if side == "manual_review" and business_score != spatial_score:
        stronger = "business" if business_score > spatial_score else "spatial"
        delta = abs(business_score - spatial_score)
        if delta >= 5:
            side = stronger
            province = clean_text(row.get(f"{stronger}_province"))
            status = "confirmed_by_combined_evidence"
            confidence = "medium"

    reason = (
        f"business_score={business_score} hits={business_hits}; "
        f"spatial_score={spatial_score} hits={spatial_hits}; "
        f"local_business={local_business_score} {local_business_hits}; "
        f"local_spatial={local_spatial_score} {local_spatial_hits}; "
        f"web_business={web_business_score} {web_business_hits}; "
        f"web_spatial={web_spatial_score} {web_spatial_hits}; "
        f"province_mentions={province_mentions}"
    )

    return {
        "province_review_side": side,
        "province_review_confirmed_province": province,
        "province_review_status": status,
        "province_review_confidence": confidence,
        "province_review_reason": reason,
        "business_evidence_score": str(business_score),
        "spatial_evidence_score": str(spatial_score),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-interval", type=float, default=0.4)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    df = pd.read_csv(INPUT_PATH, dtype=str, encoding="utf-8-sig", low_memory=False).fillna("")
    province_diff = df[df["diff"].eq("province_diff")].copy()
    if args.limit:
        province_diff = province_diff.head(args.limit).copy()

    cache = {} if args.refresh else load_cache()
    overrides = load_overrides()
    rows = []
    last_request_ts = 0.0

    for idx, row in province_diff.iterrows():
        companyid = clean_text(row.get("companyid"))
        entname = clean_text(row.get("ENTNAME"))
        query = f"{entname} {QUERY_SUFFIX}"

        if companyid not in cache:
            wait = args.min_interval - (time.time() - last_request_ts)
            if wait > 0:
                time.sleep(wait)
            engine, status, results, error = web_search(query)
            last_request_ts = time.time()
            cache[companyid] = {
                "companyid": companyid,
                "ENTNAME": entname,
                "query": query,
                "search_engine": engine,
                "search_status": status,
                "search_error": error,
                "results": results,
            }
            save_cache(cache)

        cached = cache[companyid]
        results = cached.get("results", [])
        decision = choose_side(row, results)
        if companyid in overrides:
            override = overrides[companyid]
            decision.update(
                {
                    "province_review_side": clean_text(override.get("province_review_side")),
                    "province_review_confirmed_province": clean_text(
                        override.get("province_review_confirmed_province")
                    ),
                    "province_review_status": clean_text(override.get("province_review_status")),
                    "province_review_confidence": clean_text(override.get("province_review_confidence")),
                    "province_review_reason": (
                        clean_text(override.get("province_review_reason"))
                        + " | auto_reason: "
                        + decision.get("province_review_reason", "")
                    ),
                }
            )

        out = row.to_dict()
        out.update(decision)
        out["province_review_query"] = cached.get("query", query)
        out["province_review_search_engine"] = cached.get("search_engine", "")
        out["province_review_search_status"] = cached.get("search_status", "")
        out["province_review_search_error"] = cached.get("search_error", "")
        for n in range(3):
            result = results[n] if n < len(results) else {}
            out[f"province_review_source_title_{n + 1}"] = result.get("title", "")
            out[f"province_review_source_url_{n + 1}"] = result.get("url", "")
            out[f"province_review_source_snippet_{n + 1}"] = result.get("snippet", "")
        if companyid in overrides:
            override = overrides[companyid]
            for n in range(1, 4):
                title = clean_text(override.get(f"province_review_source_title_{n}"))
                url = clean_text(override.get(f"province_review_source_url_{n}"))
                snippet = clean_text(override.get(f"province_review_source_snippet_{n}"))
                if title or url or snippet:
                    out[f"province_review_source_title_{n}"] = title
                    out[f"province_review_source_url_{n}"] = url
                    out[f"province_review_source_snippet_{n}"] = snippet
        rows.append(out)

        if len(rows) % 25 == 0 or len(rows) == len(province_diff):
            print(f"processed {len(rows)}/{len(province_diff)}")

    detail = pd.DataFrame(rows)
    detail.to_csv(DETAIL_OUTPUT_PATH, index=False, encoding="utf-8-sig")

    review_cols = [
        "province_review_side",
        "province_review_confirmed_province",
        "province_review_status",
        "province_review_confidence",
        "province_review_reason",
        "business_evidence_score",
        "spatial_evidence_score",
        "province_review_query",
        "province_review_search_engine",
        "province_review_search_status",
        "province_review_search_error",
        "province_review_source_title_1",
        "province_review_source_url_1",
        "province_review_source_snippet_1",
        "province_review_source_title_2",
        "province_review_source_url_2",
        "province_review_source_snippet_2",
        "province_review_source_title_3",
        "province_review_source_url_3",
        "province_review_source_snippet_3",
    ]
    for col in review_cols:
        df[col] = ""
    if not detail.empty:
        detail_indexed = detail.set_index("companyid")
        for col in review_cols:
            df.loc[df["companyid"].isin(detail_indexed.index), col] = df.loc[
                df["companyid"].isin(detail_indexed.index), "companyid"
            ].map(detail_indexed[col])
    df.to_csv(FULL_OUTPUT_PATH, index=False, encoding="utf-8-sig")

    summary = detail["province_review_side"].value_counts(dropna=False).rename_axis("side").reset_index(name="rows")
    status_summary = (
        detail.groupby(["province_review_side", "province_review_status"], dropna=False)
        .size()
        .rename("rows")
        .reset_index()
    )
    print("\nprovince_diff review side summary:")
    print(summary.to_string(index=False))
    print("\nprovince_diff review status summary:")
    print(status_summary.to_string(index=False))
    print(f"\nSaved detail: {DETAIL_OUTPUT_PATH}")
    print(f"Saved full reviewed file: {FULL_OUTPUT_PATH}")
    print(f"Saved cache: {CACHE_PATH}")


if __name__ == "__main__":
    main()
