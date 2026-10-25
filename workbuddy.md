# WorkBuddy 开发过程记录（workbuddy.md）

> 本文件是「麦麦主题雷达 / mcd-theme-radar」在 WorkBuddy 中开发的对话上下文摘要，
> 用于核验本项目符合「麦当劳程序员节创意开发大赛 · WorkBuddy 联动奖励」的开发条件。
>
> - 开发工具：WorkBuddy（Agent 模式，MCP 连接器 `mcd-mcp`）
> - 开发时间：2026-10-24 17:00 — 2026-10-25 11:00（UTC+8）
> - 仓库：<https://github.com/HolmesZ/mcd-theme-radar>
> - 在线演示：<https://holmesz.github.io/mcd-theme-radar/>

---

## 一、需求起点

用户在 WorkBuddy 中提出的原始需求（意译，保留关键约束）：

> 「麦当劳 App 只能看门店列表，看不到哪家店在办什么主题活动、这周末还有没有位。
> 想做一个东西：问一句话，就给我一张这个城市的麦当劳主题活动地图。
> 城市可以是我说的任意一座。」

由此确定三条硬约束：

| 约束 | 来源 |
|---|---|
| 数据必须来自麦当劳官方 MCP，不能编 | 用户要求「不能有假数据」 |
| 交付物要能直接给非技术用户看 | 用户说「发给朋友也能打开」 |
| agent 能自然语言驱动，不要求用户背命令行 | 用户要求「我说城市就行」 |

---

## 二、开发阶段与关键对话

### 阶段 1 · 摸清 MCP 能力边界（10-24 17:00–19:00）

**提问**：「麦当劳 MCP 里哪些工具能拿到门店坐标和活动信息？」

**过程**：在 WorkBuddy 中通过 `mcd-mcp` 连接器逐个试调 20+ 工具，记录真实返回字段。
**结论**（写进 `MCP_INTEGRATION.md`）：

- 只有 `query-party-store` 返回**真实经纬度**；`query-nearby-stores` 坐标恒为 `0.0`、`searchType` 实际只支持 1/2 → 不能做地图底座
- `mall-points-products` 可按 `catRuleIds` 拉到 27 个主题活动
- 坐标是 **GCJ-02**，必须配高德底图
- 场次 `price` 单位是**分**，主题 `price` 是**元**
- `partyRange` 单位是**半小时**（3 = 1.5 小时）
- 购买须知 `note` 接口明文要求**原文展示、不得改写**

**关键决策**：放弃「实时查询」方案，改为「构建期抓取 + 单文件快照」。

### 阶段 2 · 打通 Streamable HTTP 握手（10-24 19:00–21:00）

**踩坑**：直接 POST REST 调用全部失败。
**解决**：实现 JSON-RPC 2.0 三步握手（`initialize` → `notifications/initialized` → `tools/call`），携带 `mcp-session-id`，并支持 `text/event-stream` 响应按 `data:` 行切分。

**另一个坑（花了最久）**：`tools/call` 成功响应的 `content[0].text` 是「**markdown 说明 + 原始 JSON**」拼接字符串，说明里还有 `{字段}` 占位符，贪婪正则 `\{[\s\S]*\}` 解析必失败。
**解决**：从 `{"success"` 位置起用 `json.JSONDecoder().raw_decode()` 精确解析，封装进 `scripts/mcp_client.py`。

### 阶段 3 · 稀疏矩阵发现（10-24 21:00–22:30）

**提问**：「是不是所有门店都能办所有主题？」

**实测**：同一座城市，`spuId=17356` 覆盖 84 家门店、`spuId=17357` 覆盖 77 家，且**门店集合不同**；同一门店（如 1450713）跨主题坐标完全一致。
**结论**：门店 × 主题是**稀疏矩阵**，正确问法是「这家店能办哪几种」，这一条把产品从「找店」升级成「主题 × 门店匹配」——成为项目的核心叙事。

### 阶段 4 · 页面与筛选（10-24 22:30 — 10-25 02:30）

**提问**：「列表要有哪些筛选？地图怎么和列表联动？」

**迭代记录**：

1. v1：主题列表 + 地图打点 → 用户反馈「点开一个主题看不到哪些店能办」
2. v2：加「查看门店」→ 主题门店列表，列表与地图双向高亮
3. v3：用户反馈「筛选太多不好用」→ 收敛为 7 项，类型改为按本城在售主题**动态生成**下拉
4. v4：加 hash 状态（`city/spu/price/dur/type/age/people/cat/kw`）→ 一句话需求可直达筛好的视图
5. v5：加「重点 / 详细原文」两页签，`extract_highlights.py` 只切分不改写

### 阶段 5 · 全省压测与产物（10-25 02:00–03:30）

**执行**：`fetch_snapshot.py --region gd` 抓广东 21 城 → 919 家门店，耗时 7 分 42 秒，约 400 次调用。
**产物**：单文件 `dist/index.html` 635 KB，21 城下拉切换正常。
**验证**：`smoke_test.mjs` 用 Node 桩件验证渲染路径，不开浏览器即可回归。

### 阶段 6 · 比赛材料整理（10-25 10:30–11:30）

**提问**：「把 skill 按比赛要求整理，做静态网页示例，传到 GitHub 并报名。」

**执行**（均在 WorkBuddy 中完成）：

- 重写 `README.md`：项目介绍 / 目标用户 / 安装 / 使用示例 / 设计取舍 / 数据口径
- 从官方仓库原文引入 `CONTEST_DECLARATION.md`（md5 与官方一致，未改动）
- `build_map.py` 增加 `--pages`，产物同时写 `dist/index.html` 与 `docs/index.html`
- 生成 `docs/index.html` 作为 GitHub Pages 演示页
- 无头 Chrome 截取两张页面图放入 `assets/`
- 创建公开仓库、推送、开启 Pages、按官方格式提交报名 Issue

### 阶段 7 · 内地版与双模板（10-25 11:20 — 12:30）

**提问**：「我想制作一个内地版的麦麦主题雷达，标题的筛选由单一城市变成省市两级筛选。」随后追加：「这个模板，既要保留城市级的模板，也要保留省市级的模板，具体 skill 要根据用户的需求来进行选择。」

**执行**：

1. 摸清内地抓取成本：`query-party-city` 已有的 27 份城市覆盖缓存显示，内地实际只需 **5224 次**门店调用（而不是 27 × 400 的粗估），单进程约 90 分钟
2. 新增 `scripts/regions.py`：城市编码前两位 → 省份，含展示排序与分组，**省份不额外调接口**
3. `fetch_snapshot.py` 加 `--all`（内地）、`--rebuild`（免调用、从 raw 缓存重建）；抓取循环改为**城市优先、按省排序**，跑完一个省就是一份可用快照
4. 新建 `template/map_national.html`：省 › 市 两级下拉 + 内地省份气泡 + 省份排行榜；`template/map.html` **原样保留**为城市级
5. `build_map.py` 加 `--scope city|nation`：city → `dist/city.html`，nation → `dist/nation.html`（`--pages` 时 nation 写 `docs/index.html`，city 写 `docs/city.html`）
6. `smoke_test.mjs` 改为自动识别模板（页面有 `provSel` 即内地级），两种模板各跑一套断言

**踩坑**：

- 内地视图每次 `renderMap` 都重 `fitBounds`，而 `zoomend` 又触发 `renderMap` → **用户一缩放就被弹回**。加 `nvFitted` 标志，视野只自动框一次
- 省份气泡在京津、沪苏浙会重叠。按排名奇偶上下错开 7px，不完美但可读
- 内地上万门店不铺点：内地层级只画省级气泡，进省才铺门店（否则 marker 数量直接把页面拖死）

**工程取舍**：保留两套模板而不是合成一套。单城页 300 KB 打开即用，内地页 3–4 MB 多一层聚合——硬合并会两头不讨好。

---

## 三、AI 参与度说明

| 环节 | WorkBuddy 承担 | 人工判断 |
|---|---|---|
| MCP 工具测绘 | 逐个试调、核对字段、记录坑 | 决定哪些工具进方案 |
| 代码实现 | 全部脚本（8 个文件）与页面模板 | 架构取舍、口径把关 |
| 数据抓取 | 省域批采、增量合并、429 退避 | 决定只抓广东做演示 |
| 产品设计 | 筛选维度、交互流程、hash 状态 | 「不做代下单」「不做假场次」等红线 |
| 文档 | README / MCP_INTEGRATION / SKILL 话术红线 | 最终核对与发布 |

**人工把关的三条底线**（写进 `SKILL.md` 的话术红线，防止 agent 说错话）：

1. 口径只能是「可承办主题活动的餐厅」，不能写成「麦当劳全部门店」
2. 场次余位必须带「快照时点」限定，不能承诺实时
3. 购买须知只切分不改写，赠品不得当结构化字段编造

---

## 四、产出清单

| 文件 | 说明 |
|---|---|
| `SKILL.md` | Skill 主文档：城市解析、执行流程、数据链路、话术红线 |
| `scripts/mcp_client.py` | Streamable HTTP JSON-RPC 客户端（含 SSE 解析、混排 JSON 提取） |
| `scripts/make_city.py` | 一键流水线：城市 → 抓取 → 缓存 → 渲染 |
| `scripts/fetch_snapshot.py` | 城市 → 门店（增量合并，`--all` 内地 / `--rebuild` 免调用重建） |
| `scripts/fetch_spu_detail.py` | 主题详情（内容 / 赠品 / 配图） |
| `scripts/fetch_slots.py` | 日期与场次（增量合并） |
| `scripts/extract_highlights.py` | 从购买须知切套餐 / 赠品 / 预约（只切分不改写） |
| `scripts/regions.py` | 城市编码 → 省份、省份排序与分组 |
| `scripts/build_map.py` | `data + 模板 → 页面`，`--scope city\|nation`，`--pages` 输出托管版 |
| `scripts/smoke_test.mjs` | Node 桩件冒烟测试（自动识别模板） |
| `template/map.html` | 城市版模板（单城市下拉） |
| `template/map_national.html` | 内地版模板（省 › 市 两级下拉） |
| `docs/index.html` | GitHub Pages 首页：内地版演示 |
| `docs/city.html` | GitHub Pages：城市版演示 |

---

## 五、环境信息

```
OS       Windows 11 (win32)
Shell    bash (Git Bash)
Python   3.12
Node     v22.22.2
MCP      mcd-mcp → https://mcp.mcd.cn (streamablehttp)
Agent    WorkBuddy / Agent 模式
```

仓库中**不含**任何真实 Token、密钥或个人信息；`MCD_MCP_TOKEN` 一律通过环境变量注入。
