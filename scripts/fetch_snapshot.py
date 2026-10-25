"""抓取派对门店快照。

    python fetch_snapshot.py --region gd            # 广东省 21 个地级市
    python fetch_snapshot.py --cities 440100,440300 # 指定城市
    python fetch_snapshot.py --region gd --max-spu 4

输出：
    data/stores.json  门店（去重，含 spu_ids 稀疏矩阵）
    data/meta.json    抓取元信息（时间、主题、城市、调用次数）
    data/raw/*.json   原始响应缓存，可断点续跑
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from mcp_client import MCPClient

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"

GD_CITIES = {
    "440100": "广州市", "440200": "韶关市", "440300": "深圳市", "440400": "珠海市",
    "440500": "汕头市", "440600": "佛山市", "440700": "江门市", "440800": "湛江市",
    "440900": "茂名市", "441200": "肇庆市", "441300": "惠州市", "441400": "梅州市",
    "441500": "汕尾市", "441600": "河源市", "441700": "阳江市", "441800": "清远市",
    "441900": "东莞市", "442000": "中山市", "445100": "潮州市", "445200": "揭阳市",
    "445300": "云浮市",
}

CST = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def sleep_between(sec: float = 0.12):
    time.sleep(sec)


def fetch_spu_list(client: MCPClient) -> list[dict]:
    cache = DATA / "raw" / "_spu_list.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    resp = client.call(
        "mall-points-products",
        {"catRuleIds": "1>6>20,1>6>21,1>6>22,1>6>25,1>6>34,1>6>40"},
    )
    items = []
    for x in resp.get("data") or []:
        if x.get("status") != 2:  # 只保存在售
            continue
        try:
            price = float(x.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        items.append({
            "spu_id": int(x["spuId"]),
            "name": x.get("spuName", ""),
            "cat": x.get("catName", ""),
            "price": price,
            "selling": x.get("selling", ""),
            "image": x.get("spuImage", ""),
        })
    items.sort(key=lambda d: d["spu_id"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  主题 {len(items)} 个（已缓存）")
    return items


def fetch_cities(client: MCPClient, spu_id: int) -> list[dict]:
    cache = DATA / "raw" / f"_cities_{spu_id}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    resp = client.call("query-party-city", {"spuId": spu_id})
    cities = [
        {"code": str(c["code"]), "name": c["name"], "lat": c["latitude"], "lng": c["longitude"]}
        for c in resp.get("data") or []
    ]
    cache.write_text(json.dumps(cities, ensure_ascii=False), encoding="utf-8")
    sleep_between()
    return cities


def fetch_city_stores(client: MCPClient, spu_id: int, city: dict, force: bool = False) -> list[dict]:
    cache = RAW / f"{spu_id}_{city['code']}.json"
    if cache.exists() and not force:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    resp = client.call(
        "query-party-store",
        {
            "spuId": spu_id,
            "code": city["code"],
            "latitude": city["lat"],
            "longitude": city["lng"],
        },
    )
    stores = resp.get("data") or []
    cache.write_text(json.dumps(stores, ensure_ascii=False), encoding="utf-8")
    sleep_between()
    return stores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="gd")
    ap.add_argument("--cities", default="")
    ap.add_argument("--max-spu", type=int, default=0, help="只抓前 N 个主题（调试用）")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    target = dict(GD_CITIES) if args.region == "gd" else {}
    if args.cities:
        target = {c: target.get(c, c) for c in args.cities.split(",") if c}

    client = MCPClient()
    print(f"[1/3] 主题清单")
    spus = fetch_spu_list(client)
    if args.max_spu:
        spus = spus[: args.max_spu]

    print(f"[2/3] 主题覆盖城市")
    plan: list[tuple[dict, list[dict]]] = []
    for spu in spus:
        cities = [c for c in fetch_cities(client, spu["spu_id"]) if c["code"] in target]
        print(f"  {spu['spu_id']:>6} {spu['name'][:16]:<18} 覆盖广东 {len(cities):>2} 城")
        if cities:
            plan.append((spu, cities))

    total = sum(len(c) for _, c in plan)
    print(f"[3/3] 门店抓取：{total} 次调用")
    merged: dict[str, dict] = {}
    done = 0
    for spu, cities in plan:
        for city in cities:
            done += 1
            try:
                stores = fetch_city_stores(client, spu["spu_id"], city, force=args.force)
            except Exception as e:  # 单城失败不阻断
                print(f"  ! {spu['spu_id']}/{city['name']} 失败：{e}")
                continue
            for s in stores:
                code = str(s.get("code", ""))
                if not code:
                    continue
                rec = merged.get(code)
                if rec is None:
                    rec = merged[code] = {
                        "code": code,
                        "name": s.get("name", ""),
                        "short": s.get("shortName", ""),
                        "address": s.get("address", ""),
                        "city": city["code"],
                        "city_name": s.get("cityName", city["name"]),
                        "lat": s.get("latitude"),
                        "lng": s.get("longitude"),
                        "biz": s.get("businessStatus"),
                        "online": s.get("onlineBusinessStatus"),
                        "spus": [],
                    }
                if spu["spu_id"] not in rec["spus"]:
                    rec["spus"].append(spu["spu_id"])
            if done % 20 == 0 or done == total:
                print(f"  {done}/{total}  门店 {len(merged)}")

    # ---- 增量合并：本次抓的城市覆盖旧记录，其它城市原样保留 ----
    new_stores = [s for s in merged.values() if s["lat"] and s["lng"]]
    new_cities = {s["city"] for s in new_stores}

    store_path = DATA / "stores.json"
    old = {}
    if store_path.exists():
        try:
            for s in json.loads(store_path.read_text(encoding="utf-8"))["stores"]:
                if s.get("city") not in new_cities:
                    old[s["code"]] = s
        except Exception:
            old = {}

    keep = {s["code"]: s for s in new_stores}
    keep.update(old)
    stores = sorted(keep.values(), key=lambda s: (s["city"], -len(s["spus"]), s["code"]))

    store_path.write_text(
        json.dumps({"snapshot_at": now_iso(), "stores": stores}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    city_names = {}
    for s in stores:
        city_names.setdefault(s["city"], s["city_name"])
    (DATA / "meta.json").write_text(
        json.dumps({
            "snapshot_at": now_iso(),
            "cities": [{"code": k, "name": v} for k, v in sorted(city_names.items())],
            "spus": spus,
            "stats": {
                "calls": total,
                "stores": len(stores),
                "city_count": len(city_names),
            },
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n本次：{len(new_stores)} 家门店 / {len(new_cities)} 城")
    print(f"缓存：{len(stores)} 家 / {len(city_names)} 城（含历史）→ {store_path}")


if __name__ == "__main__":
    sys.exit(main())
