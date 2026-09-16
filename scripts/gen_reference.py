"""从光伏测试集为每个缺陷代码挑选参照样例(产线标注框),拷图进 static/ref/。

用法(在光伏数据仓库同级或指定路径):
    python scripts/gen_reference.py --test-root "<光伏仓库>/分类数据/硅片分类数据/硅片分类数据/测试集"
产物:static/ref/reference.json + static/ref/<stem>.png(每代码 2 张)
"""
from __future__ import annotations

import argparse
import json
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "ref"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-root", required=True)
    ap.add_argument("--per-code", type=int, default=2)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    by_code: dict[str, list] = defaultdict(list)
    for xf in sorted(Path(args.test_root).rglob("*.xml")):
        r = ET.parse(xf).getroot()
        stem = Path(r.find("filename").text).stem
        png = xf.with_name(stem + ".png")
        if not png.exists():
            continue
        for obj in r.findall("object"):
            code = obj.find("name").text.strip()
            b = obj.find("bndbox")
            by_code[code].append({
                "stem": stem, "png": png,
                "box": {"code": code,
                        "x0": int(float(b.find("xmin").text)),
                        "y0": int(float(b.find("ymin").text)),
                        "x1": int(float(b.find("xmax").text)),
                        "y1": int(float(b.find("ymax").text))},
            })

    ref: dict[str, list] = {}
    copied = 0
    for code, items in sorted(by_code.items()):
        # 优先框多的图(信息量大),稳定排序
        items.sort(key=lambda it: it["stem"])
        chosen, seen = [], set()
        for it in items:
            if it["stem"] in seen:
                continue
            seen.add(it["stem"])
            chosen.append(it)
            if len(chosen) >= args.per_code:
                break
        ref[code] = []
        for it in chosen:
            dst = OUT / (it["stem"] + ".png")
            if not dst.exists():
                shutil.copyfile(it["png"], dst)
                copied += 1
            ref[code].append({"img": it["stem"] + ".png", "stem": it["stem"],
                              "boxes": [x["box"] for x in items if x["stem"] == it["stem"]]})
    (OUT / "reference.json").write_text(
        json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")
    print("codes:", len(ref), "images copied:", copied)


if __name__ == "__main__":
    main()
