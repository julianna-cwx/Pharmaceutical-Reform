import csv
import struct
from collections import Counter
from pathlib import Path


ROOT = Path(r"D:\Hospital_Pharmacy program")
INPUT_PATH = (
    ROOT
    / "data"
    / "hospital_pharmacy"
    / "hospital_pharm_restaurant_panel_2012_2019_with_ntl.csv"
)
COUNTY_DBF = (
    ROOT
    / "data"
    / "county"
    / "controls"
    / "county_boundaries"
    / "counties19.dbf"
)
OUTPUT_PATH = (
    ROOT
    / "data"
    / "hospital_pharmacy"
    / "hospital_pharm_restau__with_ntl.csv"
)
DIFF_PATH = (
    ROOT
    / "data"
    / "hospital_pharmacy"
    / "hospital_pharm_restau__with_ntl_county_id_diff.csv"
)
UNMATCHED_PATH = (
    ROOT
    / "data"
    / "hospital_pharmacy"
    / "hospital_pharm_restau__with_ntl_unmatched.csv"
)

PROVINCE_FIELD = "\u7701"
CITY_FIELD = "\u5e02"


def read_dbf(path: Path):
    with path.open("rb") as handle:
        header = handle.read(32)
        record_count = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]

        fields = []
        while True:
            first_byte = handle.read(1)
            if first_byte == b"\r":
                break
            descriptor = first_byte + handle.read(31)
            raw_name = descriptor[:11].split(b"\x00", 1)[0]
            fields.append((raw_name.decode("utf-8", "replace"), descriptor[16]))

        handle.seek(header_length)
        for _ in range(record_count):
            record = handle.read(record_length)
            if not record or record[:1] == b"\x1a":
                break
            if record[:1] == b"*":
                continue

            offset = 1
            row = {}
            for name, length in fields:
                value = record[offset : offset + length]
                row[name] = value.decode("utf-8", "replace").strip()
                offset += length
            yield row


def normalize_code(value: str) -> str:
    value = value.strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value.zfill(6) if value.isdigit() else value


def main() -> None:
    county_lookup = {}
    duplicate_keys = set()
    for county in read_dbf(COUNTY_DBF):
        key = (county[PROVINCE_FIELD], county[CITY_FIELD], county["NAME"])
        if key in county_lookup and county_lookup[key] != county["PAC"]:
            duplicate_keys.add(key)
        county_lookup[key] = county["PAC"]

    if duplicate_keys:
        raise ValueError(f"Duplicate province-city-county keys: {len(duplicate_keys)}")

    changed_pairs = Counter()
    unmatched_rows = []
    total_rows = 0
    matched_rows = 0
    unchanged_rows = 0
    changed_rows = 0

    with INPUT_PATH.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or "county_id" not in reader.fieldnames:
            raise ValueError("Input CSV does not contain county_id")

        with OUTPUT_PATH.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=reader.fieldnames)
            writer.writeheader()

            for row in reader:
                total_rows += 1
                province = row["spatial_province"].strip()
                city = row["spatial_city"].strip()
                county = row["spatial_county"].strip()
                old_code = normalize_code(row["county_id"])
                new_code = county_lookup.get((province, city, county))

                if new_code is None:
                    row["county_id"] = old_code
                    unmatched_rows.append(
                        {
                            "hospital_id": row["hospital_id"],
                            "ENTNAME": row["ENTNAME"],
                            "year": row["year"],
                            "spatial_province": province,
                            "spatial_city": city,
                            "spatial_county": county,
                            "retained_county_id": old_code,
                            "reason": "blank spatial_county" if not county else "not found",
                        }
                    )
                else:
                    matched_rows += 1
                    new_code = normalize_code(new_code)
                    row["county_id"] = new_code
                    if old_code == new_code:
                        unchanged_rows += 1
                    else:
                        changed_rows += 1
                        changed_pairs[(province, city, county, old_code, new_code)] += 1

                writer.writerow(row)

    with DIFF_PATH.open("w", encoding="utf-8-sig", newline="") as target:
        fieldnames = [
            "spatial_province",
            "spatial_city",
            "spatial_county",
            "old_county_id",
            "new_county_id",
            "row_count",
        ]
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for key, row_count in sorted(changed_pairs.items()):
            province, city, county, old_code, new_code = key
            writer.writerow(
                {
                    "spatial_province": province,
                    "spatial_city": city,
                    "spatial_county": county,
                    "old_county_id": old_code,
                    "new_county_id": new_code,
                    "row_count": row_count,
                }
            )

    with UNMATCHED_PATH.open("w", encoding="utf-8-sig", newline="") as target:
        fieldnames = [
            "hospital_id",
            "ENTNAME",
            "year",
            "spatial_province",
            "spatial_city",
            "spatial_county",
            "retained_county_id",
            "reason",
        ]
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unmatched_rows)

    print(f"total_rows={total_rows}")
    print(f"matched_rows={matched_rows}")
    print(f"unchanged_rows={unchanged_rows}")
    print(f"changed_rows={changed_rows}")
    print(f"unmatched_rows={len(unmatched_rows)}")
    print(f"changed_pairs={len(changed_pairs)}")
    print(f"output={OUTPUT_PATH}")
    print(f"diff={DIFF_PATH}")
    print(f"unmatched={UNMATCHED_PATH}")


if __name__ == "__main__":
    main()
