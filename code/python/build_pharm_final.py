from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd


BASE_DIR = Path(r"D:\Hospital_Pharmacy program")
INPUT_DIR = BASE_DIR / "data" / "pharmacy" / "renew_pharmacy_data"
OUTPUT_DIR = BASE_DIR / "data" / "pharmacy" / "pharm_final"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

INPUT_PATTERN = "renew_pharmacy_dzdp_pharmacies_*.csv"

PHARMACY_KEYWORDS = [
    "药店", "药房", "药铺", "大药房", "医药", "药业", "药品", "药材", "中药",
    "西药", "国药", "医保", "益丰", "老百姓", "一心堂", "海王星辰",
    "同仁堂", "漱玉平民", "张仲景",
]
STRONG_PHARMACY_KEYWORDS = ["药店", "药房", "药铺", "大药房", "医药", "药业", "药品"]

NON_PHARMACY_NAME_KEYWORDS = [
    "停车场", "公寓", "酒店", "宾馆", "旅馆", "民宿", "餐厅", "饭店",
    "酒楼", "小吃", "面馆", "火锅", "烧烤", "咖啡", "奶茶", "蛋糕",
    "甜品", "超市", "便利店", "商场", "购物中心", "市场", "书店",
    "服装", "鞋", "眼镜", "美容", "美发", "美甲", "足浴", "按摩",
    "养生馆", "会所", "KTV", "网吧", "影院", "培训", "学校", "幼儿园",
    "银行", "ATM", "物流", "快递", "洗衣", "维修", "照相", "宠物",
    "动物", "兽药", "鱼药", "农药", "农资", "化肥", "种子", "饲料",
]

PHARMACY_SMALL_CATES = {"药店", "药房"}
MEDICAL_BIG_CATES = {"医疗健康"}
WEAK_MEDICAL_SMALL_CATES = {
    "中医", "中医机构", "其他医疗", "综合诊所", "综合门诊", "医疗器械",
    "社区医院", "医院", "体检中心", "康复疗养",
}
NON_PHARMACY_BIG_CATES = {
    "美食", "爱车", "丽人", "休闲娱乐", "其它", "教育培训", "酒店",
    "运动健身", "亲子", "结婚", "家装", "旅游", "生活服务",
}
NON_PHARMACY_SMALL_CATE_KEYWORDS = [
    "停车场", "民宿", "公寓", "酒店", "宾馆", "快餐", "小吃", "中餐",
    "火锅", "烧烤", "咖啡", "甜品", "食品", "保健品", "滋补品",
    "书店", "超市", "便利", "美发", "美容", "化妆品", "足疗", "按摩",
    "银行", "物流", "快递", "公司企业", "社区服务",
]


def read_csv_auto(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding, low_memory=False)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Unable to read {path}")


def as_text(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip()


def contains_any(series: pd.Series, keywords: list[str]) -> pd.Series:
    pattern = "|".join(re.escape(keyword) for keyword in keywords)
    return series.str.contains(pattern, regex=True, na=False)


def append_reason(target: pd.Series, mask: pd.Series, reason: str) -> None:
    target.loc[mask] = np.where(
        target.loc[mask].eq(""),
        reason,
        target.loc[mask] + ";" + reason,
    )


def score_pharmacy_realness(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    name = as_text(out.get("name", pd.Series("", index=out.index)))
    big_cate = as_text(out.get("big_cate", pd.Series("", index=out.index)))
    small_cate = as_text(out.get("small_cate", pd.Series("", index=out.index)))

    score = pd.Series(50, index=out.index, dtype="float64")
    reason = pd.Series("", index=out.index, dtype="string")

    has_pharmacy_keyword = contains_any(name, PHARMACY_KEYWORDS)
    has_strong_pharmacy_keyword = contains_any(name, STRONG_PHARMACY_KEYWORDS)
    small_is_pharmacy = small_cate.isin(PHARMACY_SMALL_CATES)
    big_is_medical = big_cate.isin(MEDICAL_BIG_CATES)
    small_is_weak_medical = small_cate.isin(WEAK_MEDICAL_SMALL_CATES)
    name_has_non_pharmacy = contains_any(name, NON_PHARMACY_NAME_KEYWORDS)
    small_has_non_pharmacy = contains_any(small_cate, NON_PHARMACY_SMALL_CATE_KEYWORDS)
    big_is_non_pharmacy = big_cate.isin(NON_PHARMACY_BIG_CATES)

    score += has_pharmacy_keyword.astype(int) * 30
    append_reason(reason, has_pharmacy_keyword, "名称含药店/药房/医药等药店关键词:+30")

    score += has_strong_pharmacy_keyword.astype(int) * 10
    append_reason(reason, has_strong_pharmacy_keyword, "名称含强药店关键词:+10")

    score += small_is_pharmacy.astype(int) * 25
    append_reason(reason, small_is_pharmacy, "小类为药店/药房:+25")

    score += (big_is_medical & ~small_is_pharmacy).astype(int) * 10
    append_reason(reason, big_is_medical & ~small_is_pharmacy, "大类为医疗健康:+10")

    shopping_pharmacy = big_cate.eq("购物") & small_is_pharmacy
    score += shopping_pharmacy.astype(int) * 15
    append_reason(reason, shopping_pharmacy, "购物大类但小类为药店/药房:+15")

    score += small_is_weak_medical.astype(int) * 5
    append_reason(reason, small_is_weak_medical, "小类为弱医疗相关:+5")

    no_pharmacy_keyword = ~has_pharmacy_keyword
    score -= no_pharmacy_keyword.astype(int) * 30
    append_reason(reason, no_pharmacy_keyword, "名称缺少药店关键词:-30")

    score -= name_has_non_pharmacy.astype(int) * 45
    append_reason(reason, name_has_non_pharmacy, "名称含停车场/餐饮/酒店等非药店关键词:-45")

    category_non_pharmacy = (big_is_non_pharmacy | small_has_non_pharmacy) & ~small_is_pharmacy
    score -= category_non_pharmacy.astype(int) * 40
    append_reason(reason, category_non_pharmacy, "类别指向非药店业态:-40")

    parking_or_hotel = small_cate.str.contains("停车场|民宿|公寓|酒店|宾馆", regex=True, na=False)
    score -= parking_or_hotel.astype(int) * 20
    append_reason(reason, parking_or_hotel, "停车场/住宿类强排除:-20")

    old_pred = pd.to_numeric(out.get("is_real_prediction", pd.Series(np.nan, index=out.index)), errors="coerce")
    old_conf = pd.to_numeric(out.get("prediction_confidence", pd.Series(np.nan, index=out.index)), errors="coerce")
    old_high_real = old_pred.eq(1) & old_conf.ge(0.90)
    old_low_real = old_pred.eq(1) & old_conf.lt(0.70)
    score += old_high_real.astype(int) * 5
    append_reason(reason, old_high_real, "旧模型高置信真药店:+5")
    score -= old_low_real.astype(int) * 5
    append_reason(reason, old_low_real, "旧模型置信度偏低:-5")

    score = score.clip(lower=0, upper=100).round().astype("int16")
    out["pharmacy_realness_score_100"] = score
    out["is_real_pharmacy"] = score.ge(60).astype("int8")
    out["realness_label"] = np.where(out["is_real_pharmacy"].eq(1), "真药店", "假药店")
    out["realness_reason"] = reason.mask(reason.eq(""), "无规则触发")
    return out


def process_file(path: Path) -> dict[str, object]:
    df = read_csv_auto(path)
    total_rows = len(df)

    if "is_fake_pharmacy" in df.columns:
        fake_flag = pd.to_numeric(df["is_fake_pharmacy"], errors="coerce").fillna(0).eq(1)
    else:
        fake_flag = pd.Series(False, index=df.index)

    filtered = df.loc[~fake_flag].copy()
    scored = score_pharmacy_realness(filtered)

    year_match = re.search(r"(\d{4})", path.stem)
    year = year_match.group(1) if year_match else path.stem
    out_path = OUTPUT_DIR / path.name
    scored.to_csv(out_path, index=False, encoding="utf-8-sig")

    true_count = int(scored["is_real_pharmacy"].sum())
    false_count = int(len(scored) - true_count)
    summary = {
        "year": year,
        "input_rows": total_rows,
        "removed_is_fake_pharmacy_1": int(fake_flag.sum()),
        "scored_rows": len(scored),
        "real_pharmacy_count": true_count,
        "fake_pharmacy_count_after_scoring": false_count,
        "real_share_after_scoring": true_count / len(scored) if len(scored) else np.nan,
        "output_file": str(out_path),
    }
    print(
        f"{year}: input={total_rows:,}, removed={int(fake_flag.sum()):,}, "
        f"scored={len(scored):,}, real={true_count:,}, fake={false_count:,}"
    )
    return summary


def main() -> None:
    files = sorted(INPUT_DIR.glob(INPUT_PATTERN))
    if not files:
        raise FileNotFoundError(f"No files matched {INPUT_DIR / INPUT_PATTERN}")

    summaries = [process_file(path) for path in files]
    summary_df = pd.DataFrame(summaries)
    summary_path = OUTPUT_DIR / "pharm_final_summary_2012_2022.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"saved summary: {summary_path}")


if __name__ == "__main__":
    main()
