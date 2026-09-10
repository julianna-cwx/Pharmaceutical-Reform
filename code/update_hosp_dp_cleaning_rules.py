from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd


BASE = Path(r"D:\Hospital_Pharmacy program")
CLEANED_DIR = BASE / "data" / "hospital" / "hosp_dp" / "cleaned"
RULE_VERSION = "hospital_category_score_v3_2026-07-14"


HOSPITAL_SMALL_CATE = {
    "医院",
    "综合医院",
    "中医",
    "其他医疗",
    "急救中心",
    "综合门诊",
    "骨科",
    "眼科医院",
    "康复疗养",
    "眼科",
    "妇科",
    "社区医院",
    "妇幼医院",
    "妇科医院",
    "精神卫生机构",
    "肛肠科",
    "儿童医院",
    "皮肤科",
    "肿瘤防治",
    "男科",
    "皮肤病医院",
    "传染病科",
    "脑科/神经科",
    "耳鼻喉医院",
    "耳鼻喉科",
    "心血管",
    "肾科",
    "辅助生殖机构",
    "胸/肺科",
    "肛肠科医院",
    "男科医院",
    "产科医院",
    "心血管医院",
    "综合诊所",
    "不孕不育",
    "孕产护理",
}

GENERIC_MEDICAL_SMALL_CATE = {"医疗", "医疗健康"}

COSMETIC_PATTERN = re.compile(
    "整形|医学美容|医疗美容|美容整形|医美|植发|脱毛|美胸|丰胸|纹绣|纹身|皮肤管理|"
    "美容/SPA|美容/美发|SPA美体|美甲|美睫|化妆品|美容院|美容中心"
)
DENTAL_PATTERN = re.compile("口腔|齿科|牙科|牙医|牙病|正畸|种植牙|牙齿")
CHECKUP_PATTERN = re.compile("体检中心|体检")
STORE_BRANCH_PATTERN = re.compile(r"[（(][^）)]*店[^）)]*[）)]")
HOSPITAL_NAME_PATTERN = re.compile(
    "医院|卫生院|保健院|妇幼|门诊部|门诊|诊所|医馆|中医院|卫生服务中心|康复中心|急救中心"
)


def safe_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str)


def update_file(path: Path) -> dict:
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    old_is_hospital = pd.to_numeric(df.get("is_hospital"), errors="coerce").fillna(0).astype(int)

    name = safe_text(df["name"])
    small = safe_text(df["small_cate"])
    big = safe_text(df["big_cate"])

    is_cosmetic = small.str.contains(COSMETIC_PATTERN, regex=True) | name.str.contains(COSMETIC_PATTERN, regex=True)
    is_dental = small.str.contains(DENTAL_PATTERN, regex=True) | name.str.contains(DENTAL_PATTERN, regex=True)
    is_checkup = small.str.contains(CHECKUP_PATTERN, regex=True) | name.str.contains(CHECKUP_PATTERN, regex=True)
    is_maternity_care = small.eq("孕产护理")
    has_store_suffix = name.str.contains(STORE_BRANCH_PATTERN, regex=True)
    has_hospital_name = name.str.contains(HOSPITAL_NAME_PATTERN, regex=True)
    store_hospital = has_store_suffix & has_hospital_name
    small_hospital = small.isin(HOSPITAL_SMALL_CATE)
    generic_medical_with_hospital_name = small.isin(GENERIC_MEDICAL_SMALL_CATE) & has_hospital_name

    final_is_hospital = pd.Series(0, index=df.index, dtype="int64")
    final_score = pd.Series(0, index=df.index, dtype="int64")
    reason = pd.Series("small_cate与医院无关或未命中医院规则", index=df.index, dtype="object")

    base_hospital = small_hospital | generic_medical_with_hospital_name
    final_is_hospital.loc[base_hospital] = 1
    final_score.loc[base_hospital] = 85
    reason.loc[base_hospital] = "small_cate为医院相关类别或医疗类名称含医院核心词"

    # 整形、医美、美容类优先排除；口腔齿科和体检中心在下一步强制纳入。
    final_is_hospital.loc[is_cosmetic] = 0
    final_score.loc[is_cosmetic] = 0
    reason.loc[is_cosmetic] = "整形/医美/美容类，按规则视为非医院"

    final_is_hospital.loc[is_maternity_care] = 1
    final_score.loc[is_maternity_care] = 85
    reason.loc[is_maternity_care] = "small_cate=孕产护理，暂按医院处理"

    strong_hospital = is_dental | is_checkup | (store_hospital & ~is_cosmetic)
    final_is_hospital.loc[strong_hospital] = 1
    final_score.loc[strong_hospital] = 100
    reason.loc[strong_hospital & is_dental] = "口腔/齿科/牙科相关，按规则视为医院，score=100"
    reason.loc[strong_hospital & is_checkup & ~is_dental] = "体检中心/体检相关，暂按医院处理，score=100"
    reason.loc[strong_hospital & store_hospital & ~is_dental & ~is_checkup] = "名称含医院核心词且括号内为店名，按规则视为医院，score=100"

    df["hospital_score"] = final_score
    df["is_hospital"] = final_is_hospital
    df["score_reason"] = reason
    df["rule_version"] = RULE_VERSION

    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)

    new_hospital = int(final_is_hospital.eq(1).sum())
    return {
        "file": path.name,
        "rows": int(len(df)),
        "old_is_hospital_rows": int(old_is_hospital.eq(1).sum()),
        "new_is_hospital_rows": new_hospital,
        "delta_is_hospital_rows": int(new_hospital - old_is_hospital.eq(1).sum()),
        "dental_hospital_rows": int((is_dental & final_is_hospital.eq(1)).sum()),
        "checkup_hospital_rows": int((is_checkup & final_is_hospital.eq(1)).sum()),
        "maternity_care_hospital_rows": int((is_maternity_care & final_is_hospital.eq(1)).sum()),
        "store_branch_hospital_rows": int((store_hospital & final_is_hospital.eq(1)).sum()),
        "cosmetic_nonhospital_rows": int((is_cosmetic & final_is_hospital.eq(0)).sum()),
        "unrelated_nonhospital_rows": int(final_is_hospital.eq(0).sum()),
    }


def main() -> None:
    summaries = []
    for path in sorted(CLEANED_DIR.glob("hosp_dp_*_scored.csv")):
        print(f"Updating {path.name}...", flush=True)
        summaries.append(update_file(path))

    summary = pd.DataFrame(summaries)
    total = {
        "file": "ALL",
        "rows": int(summary["rows"].sum()),
        "old_is_hospital_rows": int(summary["old_is_hospital_rows"].sum()),
        "new_is_hospital_rows": int(summary["new_is_hospital_rows"].sum()),
        "delta_is_hospital_rows": int(summary["delta_is_hospital_rows"].sum()),
        "dental_hospital_rows": int(summary["dental_hospital_rows"].sum()),
        "checkup_hospital_rows": int(summary["checkup_hospital_rows"].sum()),
        "maternity_care_hospital_rows": int(summary["maternity_care_hospital_rows"].sum()),
        "store_branch_hospital_rows": int(summary["store_branch_hospital_rows"].sum()),
        "cosmetic_nonhospital_rows": int(summary["cosmetic_nonhospital_rows"].sum()),
        "unrelated_nonhospital_rows": int(summary["unrelated_nonhospital_rows"].sum()),
    }
    summary = pd.concat([summary, pd.DataFrame([total])], ignore_index=True)
    summary.to_csv(CLEANED_DIR / "hospital_cleaning_rule_summary.csv", index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
