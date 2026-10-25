"""行政区划：城市编码 → 省份，以及省份排序/命名。

城市编码是国标 6 位行政区划码，前两位即省级代码。
省份名用短名（「广东」而非「广东省」）给 UI 用，全名留作副标题。
"""

from __future__ import annotations

# 省级代码（前两位）→ (短名, 全名)
PROVINCES: dict[str, tuple[str, str]] = {
    "11": ("北京", "北京市"),
    "12": ("天津", "天津市"),
    "13": ("河北", "河北省"),
    "14": ("山西", "山西省"),
    "15": ("内蒙古", "内蒙古自治区"),
    "21": ("辽宁", "辽宁省"),
    "22": ("吉林", "吉林省"),
    "23": ("黑龙江", "黑龙江省"),
    "31": ("上海", "上海市"),
    "32": ("江苏", "江苏省"),
    "33": ("浙江", "浙江省"),
    "34": ("安徽", "安徽省"),
    "35": ("福建", "福建省"),
    "36": ("江西", "江西省"),
    "37": ("山东", "山东省"),
    "41": ("河南", "河南省"),
    "42": ("湖北", "湖北省"),
    "43": ("湖南", "湖南省"),
    "44": ("广东", "广东省"),
    "45": ("广西", "广西壮族自治区"),
    "46": ("海南", "海南省"),
    "50": ("重庆", "重庆市"),
    "51": ("四川", "四川省"),
    "52": ("贵州", "贵州省"),
    "53": ("云南", "云南省"),
    "54": ("西藏", "西藏自治区"),
    "61": ("陕西", "陕西省"),
    "62": ("甘肃", "甘肃省"),
    "63": ("青海", "青海省"),
    "64": ("宁夏", "宁夏回族自治区"),
    "65": ("新疆", "新疆维吾尔自治区"),
    "71": ("台湾", "台湾省"),
    "81": ("香港", "香港特别行政区"),
    "82": ("澳门", "澳门特别行政区"),
}

# 展示顺序：直辖市 → 华南 → 华东 → 华北 → 华中 → 西南 → 西北 → 东北
# 抓取也按这个顺序，保证前几十分钟就能凑出几个完整省份做演示。
PROVINCE_ORDER = [
    "44",  # 广东（已有缓存）
    "11", "31", "12", "50",                  # 直辖市
    "32", "33", "35", "37",                  # 华东
    "51", "53", "52",                        # 西南
    "42", "43", "41",                        # 华中
    "13", "14", "15",                        # 华北
    "61", "62", "64", "63", "65",            # 西北
    "21", "22", "23",                        # 东北
    "34", "36", "45", "46", "54", "71", "81", "82",  # 其余
]


SCOPE_LABEL = "中国大陆"

# 港澳台同属中国行政区国标编码，但不在本接口的数据域内，
# 因此单独划出来：任何「内地」口径的统计都必须排除它们。
SAR_CODES = {"71", "81", "82"}

def mainland_codes() -> list[str]:
    """中国内地 31 个省级行政区代码（不含港澳台）。"""
    return [c for c in PROVINCES if c not in SAR_CODES]


def missing_provinces(covered: list[str]) -> list[dict]:
    """内地 31 省级行政区里，本次快照没有可承办门店的那些。

    这是「有麦当劳餐厅」与「有可承办主题活动的餐厅」的区别：
    青海等地有门店，但接口里没有任何一家配置为可承办，必须如实标出来，
    不能让页面看起来像全国每个省都覆盖了。
    """
    have = {str(c)[:2] for c in covered}
    out = []
    for code in mainland_codes():
        if code in have:
            continue
        short, full = PROVINCES[code]
        out.append({"code": code, "name": short, "full": full, "n": 0})
    return out


def province_code(city_code: str) -> str:
    """城市编码 → 省份代码。直辖市等 6 位码同样适用。"""
    return str(city_code)[:2]


def province_name(city_code: str) -> str:
    """城市编码 → 省份短名；未知码返回「其他」。"""
    return PROVINCES.get(province_code(city_code), ("其他", "其他"))[0]


def province_rank(city_code: str) -> int:
    """省份展示顺序，让下拉框按地理分区而不是拼音排。"""
    pc = province_code(city_code)
    try:
        return PROVINCE_ORDER.index(pc)
    except ValueError:
        return len(PROVINCE_ORDER)


def group_by_province(cities: list[dict]) -> list[dict]:
    """城市列表 → 省份分组，供前端两级下拉使用。

    cities: [{"code", "name", ...}]
    返回:   [{"code": "44", "name": "广东", "full": "广东省", "cities": [...]}]
    """
    buckets: dict[str, list[dict]] = {}
    for c in cities:
        buckets.setdefault(province_code(c["code"]), []).append(c)

    out = []
    for pc, items in buckets.items():
        short, full = PROVINCES.get(pc, ("其他", "其他"))
        items.sort(key=lambda x: x["code"])
        out.append({
            "code": pc,
            "name": short,
            "full": full,
            "cities": items,
            "n_cities": len(items),
        })
    out.sort(key=lambda p: (PROVINCE_ORDER.index(p["code"]) if p["code"] in PROVINCE_ORDER else 99))
    return out


if __name__ == "__main__":
    # 自检
    assert province_name("440100") == "广东"
    assert province_name("110100") == "北京"
    assert province_name("310000") == "上海"
    assert province_name("999999") == "其他"
    ml = mainland_codes()
    assert len(ml) == 31, f"内地省级行政区应为 31 个，实得 {len(ml)}"
    assert not (set(ml) & SAR_CODES)
    miss = missing_provinces(["110100", "440100"])
    print("regions.py 自检通过：", len(PROVINCES), "个省级行政区 /",
          "内地", len(ml), "个 /", "示例零覆盖", [m["name"] for m in miss][:3])
