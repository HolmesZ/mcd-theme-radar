"""按城市生成「麦麦主题雷达」页面（数据按需抓取 + 本地缓存）。

    python make_city.py --city 湛江
    python make_city.py --city 广州 --spus 4 --dates 3
    python make_city.py --city 深圳 --skip-slots      # 只抓门店，不抓场次

做的事情：
    1. 城市名 → 城市编码（query-party-city 缓存全量城市表）
    2. 确保 27 个主题活动详情已缓存（仅首次调用）
    3. 抓该城市的可承办门店（可增量合并，其它城市缓存保留）
    4. 挑门店最多的前 N 个主题，抓可约日期与场次
    5. 用「城市级模板」编译单文件页面，输出带 hash 的链接

只出单城页面。要全国 / 省 › 市 两级的页面，用：
    python fetch_snapshot.py --all
    python build_map.py --scope nation --pages

所有缓存都在 data/ 下，重复运行只补缺失部分。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from mcp_client import MCPClient

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SCRIPTS = ROOT / "scripts"
PY = sys.executable

SUFFIX = ("市", "地区", "自治州", "盟", "特别行政区", "县", "区")


def norm(name: str) -> str:
    n = name.strip()
    for suf in SUFFIX:
        if n.endswith(suf) and len(n) > len(suf):
            return n[: -len(suf)]
    return n


def load_spu_ids() -> list[int]:
    cache = RAW / "_spu_list.json"
    if cache.exists():
        return [x["spu_id"] for x in json.loads(cache.read_text(encoding="utf-8"))]
    client = MCPClient()
    resp = client.call("mall-points-products", {"catRuleIds": "1>6>20,1>6>21,1>6>22,1>6>25,1>6>34,1>6>40"})
    items = [{"spu_id": int(x["spuId"]), "name": x.get("spuName", ""), "cat": x.get("catName", ""),
              "price": x.get("price"), "status": x.get("status"), "selling": x.get("selling", ""),
              "image": x.get("spuImage", "")} for x in resp.get("data") or [] if x.get("status") == 2]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return [x["spu_id"] for x in items]


def load_cities() -> dict[str, dict]:
    """全量城市表（约 400 个），首次构建后复用。"""
    cache = RAW / "_city_index.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    ids = load_spu_ids()
    client = MCPClient()
    idx: dict[str, dict] = {}
    for spu in ids[:16]:                     # 多主题求并集，覆盖更全
        try:
            for c in client.call("query-party-city", {"spuId": spu}).get("data") or []:
                idx[str(c["code"])] = {"code": str(c["code"]), "name": c["name"],
                                       "lat": c["latitude"], "lng": c["longitude"]}
        except Exception:
            continue
        if len(idx) > 380:
            break
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    return idx


def resolve_city(query: str) -> dict:
    idx = load_cities()
    q = norm(query)
    exact = [c for c in idx.values() if norm(c["name"]) == q]
    if exact:
        return exact[0]
    part = [c for c in idx.values() if q in norm(c["name"])]
    if len(part) == 1:
        return part[0]
    if part:
        names = "、".join(c["name"] for c in part[:8])
        raise SystemExit(f"「{query}」匹配到多个城市：{names}，请写全名")
    raise SystemExit(f"没有找到「{query}」。麦当劳主题活动目前只覆盖约 {len(idx)} 个城市，"
                     f"可先跑 `python make_city.py --list` 查看支持的列表")


def run(script: str, *args: str) -> None:
    print(f"\n$ python {script} {' '.join(args)}")
    r = subprocess.run([PY, str(SCRIPTS / script), *args], cwd=SCRIPTS)
    if r.returncode != 0:
        raise SystemExit(f"{script} 执行失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", help="城市名，如 湛江 / 湛江市")
    ap.add_argument("--spus", type=int, default=3, help="抓场次的主题个数（默认 3）")
    ap.add_argument("--dates", type=int, default=3, help="每家店抓几个日期的场次（默认 3）")
    ap.add_argument("--skip-slots", action="store_true", help="跳过场次抓取")
    ap.add_argument("--list", action="store_true", help="列出支持的城市")
    args = ap.parse_args()

    if args.list:
        idx = load_cities()
        names = sorted(c["name"] for c in idx.values())
        print(f"共 {len(names)} 个城市：")
        print("、".join(names))
        return 0

    if not args.city:
        ap.error("需要 --city，例如 --city 湛江")

    city = resolve_city(args.city)
    print(f"城市：{city['name']}（{city['code']}）  {city['lat']:.4f},{city['lng']:.4f}")

    # 1) 主题详情（与城市无关，全局缓存一次）
    if not (DATA / "spus_detail.json").exists():
        run("fetch_spu_detail.py")
    else:
        print("主题详情：已缓存")

    # 1.5) 重点提炼（把购买须知里的关键句摘出来，供详情卡「重点」页签）
    if not (DATA / "highlights.json").exists():
        run("extract_highlights.py")
    else:
        print("重点摘录：已缓存")

    # 2) 门店
    run("fetch_snapshot.py", "--region", "none", "--cities", city["code"])

    # 3) 场次：挑本城门店最多的前 N 个主题
    if not args.skip_slots:
        stores = json.loads((DATA / "stores.json").read_text(encoding="utf-8"))["stores"]
        city_stores = [s for s in stores if s["city"] == city["code"]]
        cnt: dict[int, int] = {}
        for s in city_stores:
            for spu in s["spus"]:
                cnt[spu] = cnt.get(spu, 0) + 1
        top = [str(k) for k, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[: args.spus]]
        if top:
            run("fetch_slots.py", "--city", city["code"], "--spu", ",".join(top),
                "--dates", str(args.dates))
        else:
            print("本城没有可承办门店，跳过场次")

    # 4) 编译（城市级模板）
    run("build_map.py", "--scope", "city", "--city", city["code"])

    print("\n" + "=" * 56)
    print(f"页面已生成：{ROOT / 'dist' / 'city.html'}")
    print(f"直达链接：dist/city.html#city={city['code']}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
