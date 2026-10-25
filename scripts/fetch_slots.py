"""抓取可预约日期与场次（按城市）。

    python fetch_slots.py --city 440100 --spu 17356,17357,3089 --dates 3

关键结论（实测）：
- `query-party-store-date` 是「主题 × 门店」级，不同主题可约日期可能不同
- `query-party-store-session` 是「门店 × 日期」级：同一店同一天，不同主题返回的
  `id / timeStart / timeEnd / partyMin / partyMax / leftNum` 完全一致，**只有 price 随主题变**
  → 场次只需抓一次，价格按主题的 spu 价展示

产物：data/slots.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from mcp_client import MCPClient

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
CST = timezone(timedelta(hours=8))


def now_iso():
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True)
    ap.add_argument("--spu", required=True, help="逗号分隔的主题 spuId，建议 2–4 个")
    ap.add_argument("--dates", type=int, default=3, help="每个门店抓前 N 个可约日期的场次")
    ap.add_argument("--max-stores", type=int, default=0, help="调试：限制门店数")
    args = ap.parse_args()

    spus = [int(x) for x in args.spu.split(",") if x.strip()]
    stores_raw = json.loads((DATA / "stores.json").read_text(encoding="utf-8"))["stores"]
    city_stores = [s for s in stores_raw if s["city"] == args.city]
    if args.max_stores:
        city_stores = city_stores[: args.max_stores]
    print(f"城市 {args.city}：{len(city_stores)} 家门店，主题 {spus}")

    client = MCPClient()
    dates_by_spu_new: dict[str, dict[str, list[str]]] = {str(s): {} for s in spus}
    new_slots: dict[str, dict[str, list]] = {}
    calls = 0

    # 1) 日期
    plan = [(s, spu) for spu in spus for s in city_stores if spu in s["spus"]]
    print(f"[1/2] 可约日期：{len(plan)} 次调用")
    for i, (store, spu) in enumerate(plan, 1):
        code = store["code"]
        cache = RAW / f"_date_{spu}_{code}.json"
        try:
            if cache.exists():
                d = json.loads(cache.read_text(encoding="utf-8"))
            else:
                d = client.call("query-party-store-date", {"spuId": spu, "storeCode": code}).get("data") or []
                cache.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                calls += 1
        except Exception as e:
            print(f"  ! date {spu}/{code}: {e}")
            continue
        dates_by_spu_new[str(spu)][code] = [x["date"] for x in d]
        if i % 40 == 0:
            print(f"  {i}/{len(plan)}")

    # 2) 场次（门店 × 日期，去重）
    wanted: dict[str, list[str]] = {}
    for spu, m in dates_by_spu_new.items():
        for code, ds in m.items():
            merged = sorted(set(wanted.get(code, [])) | set(ds))
            wanted[code] = merged[: args.dates]

    total = sum(len(v) for v in wanted.values())
    print(f"[2/2] 场次：{total} 次调用")
    done = 0
    for code, ds in wanted.items():
        for date in ds:
            done += 1
            cache = RAW / f"_slot_{code}_{date}.json"
            try:
                if cache.exists():
                    d = json.loads(cache.read_text(encoding="utf-8"))
                else:
                    d = client.call("query-party-store-session",
                                    {"spuId": spus[0], "storeCode": code, "dateStr": date}).get("data") or []
                    cache.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                    calls += 1
            except Exception as e:
                print(f"  ! slot {code}/{date}: {e}")
                continue
            if not d:
                continue
            new_slots.setdefault(code, {})[date] = [
                {"s": x.get("timeStart"), "e": x.get("timeEnd"),
                 "min": x.get("partyMin"), "max": x.get("partyMax"), "left": x.get("leftNum")}
                for x in d
            ]
            if done % 60 == 0:
                print(f"  {done}/{total}")

    out_path = DATA / "slots.json"
    prev = {"spus": [], "dates_by_spu": {}, "slots": {}}
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 增量合并：本次抓的门店覆盖旧记录，其它城市保留
    dates_by_spu = prev.get("dates_by_spu") or {}
    merged_slots = prev.get("slots") or {}
    for spu, m in dates_by_spu_new.items():
        tgt = dates_by_spu.setdefault(spu, {})
        tgt.update(m)
    merged_slots.update(new_slots)

    out = {
        "generated_at": now_iso(),
        "cities": sorted({*prev.get("cities", []), args.city}),
        "spus": sorted({*prev.get("spus", []), *spus}),
        "dates_by_spu": dates_by_spu,
        "slots": merged_slots,
        "stats": {"calls": calls, "stores_with_slots": len(merged_slots),
                  "store_slot_days": sum(len(v) for v in merged_slots.values())},
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\n本次：{len(new_slots)} 家店有场次")
    print(f"缓存：{len(merged_slots)} 家店 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
