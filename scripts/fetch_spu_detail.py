"""抓取活动商品详情（spuId → mall-product-detail）。

    python fetch_spu_detail.py

产物：data/spus_detail.json

注意：`note`（购买须知）按接口约定只能原文展示，
这里仅做 HTML 标签 → 纯文本的呈现转换，不拆字段、不改写。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from mcp_client import MCPClient

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def html_to_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return "\n".join(line.strip() for line in s.splitlines()).strip()


def main():
    spus = json.loads((DATA / "raw" / "_spu_list.json").read_text(encoding="utf-8"))
    client = MCPClient()
    out = []
    for i, s in enumerate(spus, 1):
        spu_id = s["spu_id"]
        cache = DATA / "raw" / f"_detail_{spu_id}.json"
        if cache.exists():
            d = json.loads(cache.read_text(encoding="utf-8"))
        else:
            try:
                resp = client.call("mall-product-detail", {"spuId": spu_id})
                d = resp.get("data") or {}
                cache.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                print(f"  ! {spu_id} {s['name'][:14]} 失败：{e}")
                continue
        note = html_to_text(d.get("note", ""))
        out.append({
            "spu_id": spu_id,
            "name": s["name"],
            "cat": s["cat"],
            "price": s["price"],
            "selling": d.get("selling") or s["selling"],
            "up": (d.get("upDate") or d.get("upTime") or "")[:10],
            "down": (d.get("downDate") or d.get("downTime") or "")[:10],
            "party_people": d.get("partyPeople", ""),
            "party_age": d.get("partyAge", ""),
            "party_range": d.get("partyRange"),
            "party_type": d.get("partyType"),
            "images": d.get("images") or [],
            "note": note,
            "note_len": len(note),
        })
        print(f"  {i:>2}/{len(spus)} {spu_id:>6} {s['name'][:18]:<20} 人数={d.get('partyPeople',''):<8} 年龄={d.get('partyAge',''):<6} 时长={d.get('partyRange')} 须知{len(note)}字")

    (DATA / "spus_detail.json").write_text(
        json.dumps({"fetched_at": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                    "spus": out}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\n完成：{len(out)} 个主题详情")
    return 0


if __name__ == "__main__":
    sys.exit(main())
