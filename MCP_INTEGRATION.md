# MCP 集成说明 · 麦麦主题雷达

> 只用了 **一个 MCP 服务端**：麦当劳 `https://mcp.mcd.cn`。
> 实际用到 **6 个工具**：4 个构成地图的数据底座，2 个是场次级按需查询。

---

## 一、接入层：Streamable HTTP

普通 REST 调用会失败，必须走 JSON-RPC 2.0 的三步握手：

| 步骤 | 请求 | 说明 |
|---|---|---|
| 1 | `POST /` `method=initialize`<br>`protocolVersion=2025-03-26` | 响应头返回 `mcp-session-id`，后续请求都要带上 |
| 2 | `method=notifications/initialized`（无 id） | 通知型请求，服务端返回 202/204 |
| 3 | `method=tools/call` `{name, arguments}` | 真正的业务调用 |

请求头：

```
Authorization: Bearer <TOKEN>
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2025-03-26
mcp-session-id: <第 1 步拿到的>
```

响应可能是 `application/json`，也可能是 `text/event-stream`，后者要按 `data:` 行切分后取最后一条 JSON。

### 一个必须踩过的坑

`tools/call` 的成功响应里，`content[0].text` 是**「markdown 说明 + 原始 JSON」拼起来的字符串**，说明里还有 `{字段}` 这类表格占位符。用贪婪正则 `\{[\s\S]*\}` 截取会解析失败。

正确做法：从 `{"success"` 的位置起用 `JSONDecoder().raw_decode()` 精确解析。已封装在 `scripts/mcp_client.py`。

---

## 二、调用链

```
mall-points-products            → 有哪些活动商品（spuId 字典）
   ↓
query-party-city(spuId)         → 这个商品覆盖哪些城市（+城市中心坐标）
   ↓
query-party-store(spuId, city)  → 这个城市里哪些门店可承办（+真实经纬度）
   ↓
[合并去重] → data/stores.json
   ↓
（按需）query-party-store-date / query-party-store-session → 具体日期与场次
```

### 1. `mall-points-products` — 建主题字典

| | |
|---|---|
| 入参 | `catRuleIds = "1>6>20,1>6>21,1>6>22,1>6>25,1>6>34,1>6>40"`（生日类派对 / 主题类派对 / 麦麦体验营 / 品鉴会 / 读书会 / 积分兑换活动） |
| 出参 | 27 条 `[{spuId, spuName, catName, price, point, upTime, downTime, status, spuImage, selling}]` |
| 用途 | ① 决定要抓哪些主题（只保留 `status=2` 在售）② 页面上的主题筛选 chips、门店卡标签、价格区间全部来自这张字典 ③ `upTime/downTime` 用来说明"这是时效活动还是常设派对" |
| 调用次数 | 1 |

要点：这里的 `price` 单位是**元**，而场次接口的 `price` 是**分**，两处不能混。

### 2. `query-party-city` — 确定抓取范围

| | |
|---|---|
| 入参 | `{spuId: 6370}` |
| 出参 | 约 400 条 `[{code, name, latitude, longitude, initial, sortNo}]` |
| 用途 | ① 判断该主题在哪些城市有门店，**没有覆盖的城市不必请求**，直接砍掉大量无效调用 ② `latitude/longitude` 是下一步的必填入参——它需要一个参考点来算距离 |
| 调用次数 | 每个主题 1 次（广东用 23 次） |

实测：不同 `spuId` 的城市清单并不相同（「疯狂动物城」有拉萨，「过家家」没有），所以不能只查一次就套用到所有主题。

### 3. `query-party-store` — 拿门店坐标（核心）

| | |
|---|---|
| 入参 | `{spuId, code: "440100", latitude, longitude}` |
| 出参 | 整城门店数组 `[{code, name, shortName, address, cityCode, cityName, latitude, longitude, distance, distanceText, businessStatus, onlineBusinessStatus}]` |
| 用途 | **全项目唯一提供真实经纬度的接口**。用它做地图打点、算密度、承载"这家店能办哪几种"的稀疏矩阵 |
| 调用次数 | 广东 23 主题 × 21 城 = 399 次，耗时 7 分 42 秒 |

三个必须知道的特性：

- **一次返回整城全量，无分页**。上海 221 家、广州 180 家一次给完，按 `distance` 升序。
- **坐标是 GCJ-02**。配高德底图零偏移；配 OSM 必须纠偏，否则整体偏约 500 米。
- `businessStatus` 是**整数 1**，不是布尔值。

合并规则：以 `code` 为主键去重，一个门店累加 `spus[]`。实测同一门店跨主题坐标完全一致（如 1450713 恒为 `31.233774, 121.475816`），所以坐标是门店级事实，可安全复用。

### 4. `mall-product-detail` — 活动内容与赠品

| | |
|---|---|
| 入参 | `{spuId: 6370}` |
| 出参 | `partyAge / partyPeople / partyRange / partyType / price / images / note` 等 |
| 用途 | 门店卡上的"适龄·人数·时长·成团方式·价格"、主题图鉴的官方配图、以及可展开的「活动内容 / 含赠品明细」全部来自这里 |
| 调用次数 | 每个主题 1 次（全省 27 次） |

三个要点：

- `partyRange` 是**半小时为单位**（3 = 1.5 小时）；`partyType`：1 包场 / 2 拼团 / -1 两者都行
- 餐食组成与赠品清单都在 `note` 里，但接口明文规定 **必须原文展示，不得拆分、提取或改写为结构化字段**，也不得取其中的数值做校验 → 页面只做折叠原文
- `images[0]` 是官方主图，直接用于卡片与图鉴

### 5 & 6. `query-party-store-date` / `query-party-store-session` — 场次级

| | |
|---|---|
| 入参 | `date`: `{spuId, storeCode}`；`session`: `{spuId, storeCode, dateStr}` |
| 出参 | `date` → 7 个可约日期（**今天+3 至 今天+9**，不含今天和明天）<br>`session` → `[{timeStart, timeEnd, partyMin, partyMax, price, leftNum}]`，如 `15:30-17:00 / 5-12 人 / 5500 分 / 余 12` |
| 用途 | 回答"这周六下午还有没有位置"。**未做全省预烘**——919 家 × 7 天 = 6433 次调用，收益不值，改为用户点开某店时按需查 |

---

## 三、为什么没用另外几个工具

| 工具 | 尝试结果 | 结论 |
|---|---|---|
| `query-nearby-stores` | 坐标恒为 `0.0`；`searchType` 实际只允许 1/2（文档称 3=经纬度）；只能 city+keyword 检索 | 不能做地图底座。但它的 `reservationTimeOptions` 是营业时段与餐段窗口的唯一来源 |
| `delivery-query-addresses` / `delivery-query-stores` | 当前账号地址列表为空；判定配送范围需先 `delivery-create-address` 写地址 | 属于外送场景，与本项目无关，且涉及写操作 |
| `query-meals` / `calculate-price` / `create-order` | 点餐链路 | 与派对承办无关 |

---

## 四、业务价值（这套调用链解决了什么）

### 4.1 把「主题 × 门店」的稀疏矩阵变成可查询的产品

单看接口，每个工具只回答一个维度的问题。串起来之后才出现一个新事实：

> **门店不是「能 / 不能办派对」，而是「能办哪几种派对」。**

实测广州：`spuId=17356` 有 84 家门店、`spuId=17357` 有 77 家，**门店集合不同**；同一门店跨主题坐标完全一致。
这意味着「找一家能办某主题的店」和「这家店能办什么」是两个不同的查询，而麦当劳 App 只给了后者的列表形态、没给空间形态。

本项目的价值就是**把矩阵画在地图上**：

| 用户原问题 | 需要的接口组合 | 产品化后的答案 |
|---|---|---|
| 我家附近哪家能给孩子办生日会？ | `mall-points-products` → `query-party-city` → `query-party-store` | 地图上 84 个可点标记，按距离排序，一键导航 |
| 这个主题广州有几家店能办？ | `query-party-store(spuId, 440100)` | 「84 家店在举办」+ 门店列表 |
| 这周六下午还有位吗？ | `+ query-party-store-date` / `-session` | 具体时段、余位、单价（分→元） |
| 这个套餐到底含什么？ | `mall-product-detail` → `note` 原文切分 | 「重点」三块 + 「详细原文」兜底 |

### 4.2 三个可量化的收益

1. **信息获取成本**：从「翻 84 家门店详情页、逐个打电话」降到「打开一张图」。单城首跑 1 分 06 秒，之后命中缓存近乎零成本。
2. **调用预算可控**：城市级缓存 + `query-party-city` 前置过滤，把无效请求砍掉——没有覆盖的城市不请求。全省 21 城仅 ~400 次调用。
3. **不越权**：全程只读，不调用 `create-order` / `calculate-price` 等交易链路，不代下单、不支付，把这部分留给官方 App。

### 4.3 设计上的关键取舍

| 取舍 | 理由 |
|---|---|
| 构建期抓取，不用实时查 | 单城 200 次调用，页面打开等不了；Token 也会暴露到前端 |
| 场次按需查，不预烘全省 | 919 店 × 7 天 = 6433 次调用，收益不值 |
| 赠品/餐食只折叠原文 | 接口明文要求 `note` 原文展示、不得拆成结构化字段 |
| 不做全国一次性抓取 | 23 主题 × ~400 城 ≈ 7600 次调用、约 2.3 小时，改设计成按省扩展 |

---

## 五、调用预算与节流

- 限流 **600 次/分钟/token**，超限 429。
- 实测速率约 **1 次/秒**（0.12s 节流 + 网络往返），399 次耗时 7 分 42 秒。
- 脚本内置：城市级缓存（`data/raw/{spu}_{city}.json`）断点续跑、429 退避重试、单城失败不阻断。
- **全国实测**：27 个主题覆盖 281 城，实际需要 **5224 次**门店调用（不是「27 × 400」的粗估——`query-party-city` 前置过滤砍掉了大量无效城市，稀缺口径的主题只覆盖几十城）。单进程约 **90 分钟**；按省级优先级排序，跑完一个省就是一份可用快照。
- 想更快：拆成多个进程跑不同省份（每个进程用 `--cities` 限定），互不重叠，最后 `--rebuild` 合并。

---

## 六、复现

```bash
cd scripts
python fetch_snapshot.py --region gd      # 抓广东 21 城
python build_map.py                       # 生成 dist/index.html
```

Token 读取顺序：环境变量 `MCD_MCP_TOKEN` → `~/.workbuddy/mcp.json` 里的 `Authorization: Bearer`。
