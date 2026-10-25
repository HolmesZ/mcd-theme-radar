"""把 data/*.json + template/map.html 编译成单文件 dist/index.html。

    python build_map.py                # 缓存里所有城市
    python build_map.py --city 440800  # 只输出这一座城市（推荐）
    python build_map.py --pages        # 额外输出 docs/index.html（GitHub Pages 用）
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TPL = ROOT / "template" / "map.html"
OUT = ROOT / "dist" / "index.html"
PAGES_OUT = ROOT / "docs" / "index.html"


def js_json(obj) -> str:
    # 防止 </script> 提前闭合
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="", help="只输出该城市编码；不填则输出缓存里全部城市")
    ap.add_argument("--pages", action="store_true", help="额外写一份 docs/index.html，供 GitHub Pages 直接托管")
    args = ap.parse_args()

    stores_raw = json.loads((DATA / "stores.json").read_text(encoding="utf-8"))
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))

    stores = stores_raw["stores"]
    if args.city:
        stores = [s for s in stores if s["city"] == args.city]
        if not stores:
            raise SystemExit(f"缓存里没有城市 {args.city} 的门店，先跑 fetch_snapshot.py")
    # 只保留页面用得到的字段，压缩体积
    slim = [
        {
            "code": s["code"],
            "name": s["name"],
            "short": s.get("short") or s["name"],
            "address": s["address"],
            "city": s["city"],
            "city_name": s["city_name"],
            "lat": s["lat"],
            "lng": s["lng"],
            "biz": s["biz"],
            "spus": s["spus"],
        }
        for s in stores
    ]

    # 主题按被覆盖门店数降序，城市同理（前端已再排一次，这里保证稳定）
    hl_path = DATA / "highlights.json"
    highlights = json.loads(hl_path.read_text(encoding="utf-8")) if hl_path.exists() else {}

    detail_path = DATA / "spus_detail.json"
    detail = {}
    if detail_path.exists():
        for d in json.loads(detail_path.read_text(encoding="utf-8"))["spus"]:
            detail[d["spu_id"]] = d

    spus_out = []
    for x in sorted(meta["spus"], key=lambda x: -sum(1 for s in slim if x["spu_id"] in s["spus"])):
        d = detail.get(x["spu_id"], {})
        spus_out.append({
            "spu_id": x["spu_id"],
            "name": x["name"],
            "cat": x.get("cat", ""),
            "price": x.get("price"),
            "people": d.get("party_people", ""),
            "age": d.get("party_age", ""),
            "range": d.get("party_range"),
            "ptype": d.get("party_type"),
            "selling": d.get("selling") or x.get("selling", ""),
            "img": (d.get("images") or [""])[0],
            "note": d.get("note", ""),
            "hl": highlights.get(str(x["spu_id"]), []),
            "n": sum(1 for s in slim if x["spu_id"] in s["spus"]),
        })

    meta_out = {
        "snapshot_at": stores_raw["snapshot_at"],
        "spus": spus_out,
        "cities": [c for c in meta["cities"] if not args.city or c["code"] == args.city],
        "stats": meta["stats"],
    }

    slots_path = DATA / "slots.json"
    slots = json.loads(slots_path.read_text(encoding="utf-8")) if slots_path.exists() else {
        "generated_at": None, "spus": [], "dates_by_spu": {}, "slots": {}
    }
    if args.city:
        keep_codes = {s["code"] for s in slim}
        slots = {
            **slots,
            "slots": {k: v for k, v in (slots.get("slots") or {}).items() if k in keep_codes},
            "dates_by_spu": {
                spu: {k: v for k, v in m.items() if k in keep_codes}
                for spu, m in (slots.get("dates_by_spu") or {}).items()
            },
        }
        slots["dates_by_spu"] = {k: v for k, v in slots["dates_by_spu"].items() if v}

    html = TPL.read_text(encoding="utf-8")
    html = (html.replace("__DATA__", js_json(slim))
                .replace("__META__", js_json(meta_out))
                .replace("__SLOTS__", js_json(slots)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    if args.pages:
        PAGES_OUT.parent.mkdir(parents=True, exist_ok=True)
        PAGES_OUT.write_text(html, encoding="utf-8")

    size = OUT.stat().st_size / 1024
    print(f"已生成 {OUT}")
    if args.pages:
        print(f"已生成 {PAGES_OUT}（GitHub Pages）")
    print(f"  门店 {len(slim)} 家 / 城市 {len({s['city'] for s in slim})} 个 / 主题 {len(meta_out['spus'])} 个 / {size:.0f} KB")
    if slots.get("slots"):
        print(f"  场次：{len(slots['slots'])} 家店 / 生成于 {slots['generated_at']}")


if __name__ == "__main__":
    main()
