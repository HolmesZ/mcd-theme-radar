"""从购买须知里抽取「套餐 / 赠品 / 预约」三块重点。

原则：**只切分官方原文，不改写**。
- 套餐：定位「开心乐园餐 / 双人餐 / XX套餐」等餐组，把括号内的原文按 ＋ 、 ， 切成
  主食 / 小食 / 饮料 / 玩具 行；每行的选项就是原文里用 / 并列的字符串。
- 赠品：定位「另含 / 赠送」那句，按 、 切成一件件，数量、规格、随机说明都留在原文词上。
- 预约：按「预订 / 成团 / 退改 / 时长」四类，各取一句原文整句。

所有片段文字都来自 note，未做同义改写；页面同时保留「原文」开关和「详细原文」页签。

    python extract_highlights.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SRC = DATA / "spus_detail.json"
OUT = DATA / "highlights.json"

UNITS = "个张份套件顶枚副组对只把盒包条块袋罐双瓶杯款本面"
UNITS_CLS = "[" + UNITS + "]"
OPEN = "（(【「"
CLOSE = "）（】」"


# ---------- 基础工具 ----------

def depth_split(s: str, seps: str) -> list[str]:
    """按 seps 里的字符切分，括号内的不切。"""
    out, buf, d = [], [], 0
    for ch in s:
        if ch in OPEN:
            d += 1
        elif ch in CLOSE:
            d = max(0, d - 1)
        if ch in seps and d == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def take_paren(s: str, i: int) -> tuple[str, int]:
    """s[i] 是左括号，返回（括号内文本, 右括号后一位）。"""
    pairs = {"（": "）", "(": ")", "【": "】", "「": "」"}
    d, j = 0, i
    while j < len(s):
        if s[j] in pairs:
            d += 1
        elif s[j] in pairs.values():
            d -= 1
            if d == 0:
                return s[i + 1 : j], j + 1
        j += 1
    return s[i + 1 :], len(s)


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ，,、；;。：:")


def clean_meal_name(raw: str) -> str:
    """去掉餐组名前面的「和1份」「或1份」这类连接词。"""
    n = tidy(raw)
    n = re.sub(r"^(?:内含|包含|包括)[:：]?\s*", "", n)
    n = re.sub(r"^[和或与+＋]\s*", "", n)
    n = re.sub(r"^\d+\s*份\s*", "", n)
    return n.strip()


# ---------- 套餐 ----------

MEAL_NAME = re.compile(
    r"(开心乐园餐|亲子餐|双人餐|大人套餐|"
    r"[\u4e00-\u9fa5A-Za-z0-9™·\-\s]{2,18}?(?:套餐|四件套|三件套|3件套|两件套|单人餐))"
)

MEAL_REGION_START = re.compile(r"(内含|包含|包括|赠送)")
MEAL_REGION_END = re.compile(r"(以及沉浸式|体验券可于|沉浸式体验)")


def meal_region(note: str) -> str:
    m = MEAL_REGION_START.search(note)
    if not m:
        return ""
    tail = note[m.start() :]
    e = MEAL_REGION_END.search(tail)
    return tail[: e.start()] if e else tail[:900]


def parse_label(head: str) -> tuple[str, str, str]:
    """'主食1份（任选1）' -> ('主食', '1份', '任选1')"""
    head = tidy(head)
    pick = ""
    m = re.search(r"[（(]([^）)]*)[）)]", head)
    if m:
        pick = m.group(1).strip()
        head = (head[: m.start()] + head[m.end() :]).strip()
    qty = ""
    m = re.search(r"(\d+\s*" + UNITS_CLS + r"|半份)", head)
    if m:
        qty = m.group(1).replace(" ", "")
        head = (head[: m.start()] + head[m.end() :]).strip(" ，,、")
    return tidy(head), qty, pick


def is_toy(seg: str) -> bool:
    return bool(re.search(r"玩具", seg)) and len(seg) <= 16


def toy_part(seg: str) -> dict:
    if re.search(r"不含|无玩具", seg):
        return {"label": "玩具", "qty": "", "pick": "", "items": [{"t": "不含玩具"}]}
    m = re.search(r"(\d+\s*款|\d+\s*个)", seg)
    return {
        "label": "玩具",
        "qty": (m.group(1).replace(" ", "") if m else "1款"),
        "pick": "随机",
        "items": [{"t": "随机玩具"}],
    }


def split_items(tail: str) -> list[dict]:
    """把「A，B/C（任选1）」切成 [单品A, 选项组[B,C]]。

    原文用「/」并列的是**互斥选项**，不能拆成两件东西，否则「任选1」就丢了。
    """
    items: list[dict] = []
    for it in depth_split(tail, "，,"):
        it = tidy(it)
        if not it:
            continue
        alts = depth_split(it, "/／")
        if len(alts) > 1:
            items.append({"g": alts})
        else:
            items.append({"t": it})
    return items


def parse_meal_body(body: str) -> list[dict]:
    # 「1份大人套餐和1份开心乐园餐」这类只是组合关系，单独成一类
    if re.match(r"^\d+\s*份.*?[和或].*?\d+\s*份", body) and "：" not in body:
        return [{"label": "组成", "qty": "", "pick": "",
                 "items": [{"t": x} for x in depth_split(body, "和或")]}]

    # 「…100%苹果汁（200毫升）和1份麦辣鸡腿汉堡套餐（…）」——和/或后面接新餐组，先断开
    body = re.sub(r"[和或](?=\d+\s*份)", "｜", body)
    has_label = ("：" in body) or (":" in body)
    seps = "＋+，,；;｜" if has_label else "＋+，,；;｜、"
    parts: list[dict] = []
    for seg in depth_split(body, seps):
        seg = tidy(seg)
        if not seg:
            continue
        if is_toy(seg):
            parts.append(toy_part(seg))
            continue
        # 「和1份XX套餐」「1份XX套餐(…)」这类引用由外层 finditer 单独成组，这里丢掉
        if re.match(r"^(?:[和或与]\s*)?\d*\s*份?(?:开心乐园餐|亲子餐|双人餐|大人套餐|[^，,：:]{2,16}(?:套餐|件套|四件套))", seg):
            continue
        if "：" in seg or ":" in seg:
            head, tail = re.split(r"[：:]", seg, maxsplit=1)
            label, qty, pick = parse_label(head)
            parts.append({"label": label or "含", "qty": qty, "pick": pick,
                          "items": split_items(tail)})
            continue
        # 没有标签的片段：视为上一行的延续（如「甜香玉米杯（小）/苹果片」）
        items = split_items(seg)
        if parts and parts[-1].get("label") and parts[-1]["label"] != "玩具":
            for it in items:
                if it not in parts[-1]["items"]:
                    parts[-1]["items"].append(it)
        else:
            parts.append({"label": "含", "qty": "", "pick": "", "items": items})
    return parts


def extract_meals(note: str) -> dict:
    region = meal_region(note)
    if not region:
        return {"meals": [], "raw": ""}

    meals, seen = [], set()
    for m in MEAL_NAME.finditer(region):
        name = clean_meal_name(m.group(1))
        if not name or name in ("套餐", "餐"):
            continue
        j = m.end()
        while j < len(region) and region[j] in " \u3000":
            j += 1
        body = ""
        if j < len(region) and region[j] in "（(【":
            body, j = take_paren(region, j)
        elif re.match(r"[，,]?\s*(?:套餐)?含[:：]?", region[j : j + 12]):
            m2 = re.match(r"[，,]?\s*(?:套餐)?含[:：]?", region[j : j + 12])
            body = depth_split(region[j + m2.end() :], "；;。")[0]
        elif region[j : j + 2] in ("包括", "包含"):
            k = region.find("：", j)
            if k == -1:
                k = region.find(":", j)
            if k != -1:
                body = region[k + 1 : k + 1 + 320]
                nxt = MEAL_NAME.search(body)
                if nxt and nxt.start() > 0:
                    body = body[: nxt.start()]
        if not body:
            continue
        body = re.sub(r"^(?:包括|包含|内含|含)[:：]?\s*", "", body)
        body = re.split(r"。(?=)|赠送[:：]|体验券可于", body)[0].strip()[:240]
        # 双括号写法（（内含…））会多出一个右括号，只在确实多出来时才去掉
        if body.count("）") + body.count(")") > body.count("（") + body.count("("):
            body = re.sub(r"[）)]\s*$", "", body).strip()
        parts = parse_meal_body(body)
        if not parts:
            continue
        first = parts[0]["items"][0] if parts[0].get("items") else {}
        key = (name, first.get("t") or (first.get("g") or [""])[0])
        if key in seen:
            continue
        seen.add(key)
        meals.append({"name": name, "parts": parts, "raw": tidy(body)})
        if len(meals) >= 3:
            break
    if not meals:
        # 没有标准「XX套餐」写法时，退化成一句原文
        m = re.search(r"(?:内含|包含|包括)([^。，；]{2,40})", region)
        if m:
            meals.append({
                "name": "活动含",
                "parts": [{"label": "含", "qty": "", "pick": "",
                           "items": [{"t": tidy(m.group(1).split("以及")[0])}]}],
                "raw": tidy(m.group(0)),
            })
    return {"meals": meals, "raw": "" if meals else tidy(region[:200])}


# ---------- 赠品 ----------

GIFT_LEAD = re.compile(r"(此外[^。；]{0,40}?另含|除餐食外[^。；]{0,10}?赠送[:：]?|另含|赠送[:：]?)")


def parse_gift_item(it: str) -> dict | None:
    it = tidy(it)
    if len(it) < 3:
        return None
    sub: list[str] = []
    spec: list[str] = []
    rand: list[str] = []
    name = it
    # 从后往前摘掉所有括号，分别判断是「尺寸规格」还是「款式随机」
    for m in reversed(list(re.finditer(r"[（(]([^（）()]*)[）)]", it))):
        inner = m.group(1).strip()
        if re.search(r"含|包含", inner) and "、" in inner:
            sub = [tidy(x) for x in depth_split(inner, "、")]
        elif re.search(r"随机|款式|选一|款", inner):
            rand.insert(0, inner)
        else:
            spec.insert(0, inner)
        name = (name[: m.start()] + name[m.end() :]).strip()

    qty = ""
    qm = re.search(r"(\d+)\s*(" + UNITS_CLS + r")", name)
    if qm:
        qty = f"{qm.group(1)}{qm.group(2)}"
        name = (name[: qm.start()] + name[qm.end() :]).strip(" ，,、")
    name = name.strip("【】「」 ")

    return {
        "name": name or it,
        "qty": qty,
        "spec": " · ".join(spec),
        "rand": " · ".join(rand),
        "sub": sub,
    }


def extract_gifts(note: str) -> dict:
    m = GIFT_LEAD.search(note)
    if not m:
        return {"lead": "", "items": [], "raw": ""}
    lead = m.group(1)
    tail = note[m.end() :]
    body = ""
    for seg in re.split(r"(?<=。)", tail):
        if re.search(r"\d+\s*" + UNITS_CLS + r"|[【“]", seg):
            body = seg
            break
    body = tidy(body.split("体验券可于")[0])
    raw_items = depth_split(body, "、；;")
    # 有些须知用「，」分隔多件赠品（每件都带【】），此时按逗号再切一刀
    if len(raw_items) == 1 and (body.count("【") >= 2 or body.count("，") >= 2):
        raw_items = depth_split(body, "，,；;")
    items = [x for x in (parse_gift_item(t) for t in raw_items) if x]
    return {"lead": tidy(lead), "items": items, "raw": body}


# ---------- 预约 ----------

# 成团方式与时长已在卡片顶部的结构化字段里，预约这栏只留「要提前多久」和「怎么退改」
BOOK_RULES = [
    ("预订", r"(提前\s*\d+\s*天(预订|预约)|需提前|请提前)"),
    ("退改", r"(退订|退改|修改订单|缺席|无法退还)"),
]

# 退改的宽松兜底：只有严格关键词都没命中时才用，且要排除「拼团失败自动退款」这类成团规则
LOOSE = {"退改": r"(取消|退款)", "预订": r"(活动预约|派对预约|预约时间)"}
LOOSE_SKIP = re.compile(r"(拼团|成团|起订|最高人数)")

SKIP = re.compile(r"(条款|隐私|发票|法律|作弊|不可抗力|解释权|未成年人|公众号|热线)")


def clip(s: str, n: int = 150) -> str:
    s = re.sub(r"^[\d\s]*[).、．]\s*", "", s)
    s = tidy(s)
    if len(s) <= n:
        return s
    cut = s[:n]
    # 尽量在标点处断句，避免半句
    for p in ("，", "、", "；"):
        k = cut.rfind(p)
        if k >= n * 0.5:
            return cut[:k] + "…"
    return cut + "…"


def narrow(s: str, pat: str) -> str:
    """把整句收窄到命中的那几个分句，读起来更干净。"""
    clauses = depth_split(s, "，,")
    if len(clauses) <= 1:
        return clip(s)
    hit = [i for i, c in enumerate(clauses) if re.search(pat, c)]
    if not hit:
        return clip(s)
    return clip("，".join(clauses[hit[0] : hit[-1] + 1]))


def extract_booking(note: str) -> list[dict]:
    sents = [s for s in re.split(r"(?<=[。；\n])", note) if s.strip()]
    out, used = [], set()
    for tag, pat in BOOK_RULES:
        for i, s in enumerate(sents):
            if i in used or not re.search(pat, s) or SKIP.search(s):
                continue
            t = narrow(s, pat)
            if len(t) < 5:
                continue
            used.add(i)
            out.append({"tag": tag, "t": t})
            break

    got = {b["tag"] for b in out}
    for tag, pat in LOOSE.items():
        if tag in got:
            continue
        for i, s2 in enumerate(sents):
            if i in used or LOOSE_SKIP.search(s2) or SKIP.search(s2) or not re.search(pat, s2):
                continue
            t = narrow(s2, pat)
            if len(t) < 5:
                continue
            out.append({"tag": tag, "t": t})
            break
    return out


# ---------- 主流程 ----------

def build(note: str) -> dict:
    meal = extract_meals(note)
    gift = extract_gifts(note)
    return {
        "meals": meal["meals"],
        "meal_raw": meal["raw"],
        "gifts": gift["items"],
        "gift_lead": gift["lead"],
        "gift_raw": gift["raw"],
        "booking": extract_booking(note),
    }


def main() -> int:
    src = json.loads(SRC.read_text(encoding="utf-8"))["spus"]
    out = {str(x["spu_id"]): build(x.get("note", "")) for x in src}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    full = sum(1 for v in out.values() if v["meals"])
    gifts = sum(1 for v in out.values() if v["gifts"])
    print(f"已生成 {OUT}：{len(out)} 个主题，{full} 个解析出套餐，{gifts} 个解析出赠品")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
