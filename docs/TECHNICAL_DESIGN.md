# 天镜 SkyLens · 技术说明

> Personal weather explainer: multi-source forecasts, satellite imagery and synoptic charts,
> with LLM-grounded, provenance-linked explanations.

| 项 | 值 |
|---|---|
| 中文名 | 天镜 |
| 英文名 | SkyLens |
| 仓库 | `skylens` |
| 形态 | Web 优先 → Capacitor 套壳出 App |
| 用途 | **个人非商用**（不收费、不对外分发数据、不发布自制预报） |
| 语言栈 | Python 3.12 + TypeScript（前端） |
| LLM | DeepSeek / Qwen，OpenAI 兼容接口 |

---

## 1. 定位

**做**：给定一个地点，聚合多源天气数据、云图、天气图与环流形势，生成一份**带出处、分层次、说得出原因**的天气解释。

**不做**：

| 非目标 | 原因 |
|---|---|
| 发布自制天气预报数值 | 《气象预报发布与传播管理办法》统一发布制度 |
| 改写官方预警文案 | 26 号令第九条：不得自行更改内容和结论 |
| 全国全量覆盖 | 个人项目，先做透 1–3 个地点 |
| 实时高并发 | 单用户场景，不做水平扩展 |
| 自研数值预报 | 完全没必要，数据源够用 |

**成功标准**（用一句话检验）：对「明安图镇现在的天气及其成因」这个提问，能给出
① 带时效和来源的实况 ② 多模式预报一致性 ③ 基于 500hPa/850hPa 与天气图的成因推断
④ 明确标注哪些是观测、哪些是预报、哪些是推断 ⑤ 每个数字可点回原始来源。

---

## 2. 五条设计原则

1. **事实与解释分离**。`fact_pack` 由确定性 Python 代码组装，不经 LLM；LLM 只负责把已有事实写成人话。
2. **每个数字带 provenance**。`{value, unit, source, source_url, valid_time, fetched_at}` 是数据的最小单元，缺一不可。
3. **三层信息强制区分**：观测（observed）/ 预报（forecast）/ 推断（inference）。UI 上配色不同。
4. **Provider 可切换**。任何外部数据源都必须藏在接口后面，换源不改业务代码。
5. **官方文案只搬运不改写**。预警与官方预报原文完整并列展示，AI 只做「这是什么意思、我该怎么办」的解读。

---

## 3. 架构

```
┌─────────────────────────────────────────────────────────────┐
│ 前端（Web / Capacitor 壳内同一套代码）                        │
│  MapLibre GL + 天地图底图 + NASA GIBS 云图瓦片                 │
│  侧栏：JMA/中央气象台天气图缩略图 → 点击放大 → 外链 meteoblue  │
│  聊天：SSE 流式，回答带 [1][2] 引用，可点回数据源              │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP/SSE     (LLM key 只在服务端)
┌──────────────────────────▼──────────────────────────────────┐
│ FastAPI 后端                                                  │
│                                                              │
│  GET  /api/fact_pack?lat&lon&place   确定性组装，不走 LLM      │
│  POST /api/explain                   fact_pack → LLM → JSON   │
│  GET  /api/warnings?lat&lon          官方预警（原样搬运）      │
│  GET  /api/charts?lat&lon            天气图 URL 列表           │
│  GET  /api/healthz                                            │
│                                                              │
│  core/fact_pack.py   ── 编排 providers，产出统一事实包         │
│  core/stats.py       ── 集合统计（照搬旧仓库算法）             │
│  core/explain.py     ── 单次 LLM 调用，结构化输出              │
│  core/vocab.py       ── 中文术语/单位/分级文案表               │
│                                                              │
│  providers/（全部实现同一 Protocol，可切换/可降级）            │
│    open_meteo.py  多模式 + ensemble（spread 的唯一来源）       │
│    qweather.py    中国区要素、格点、预警（准）                 │
│    metar.py       最近机场实况（真·观测）                      │
│    geocode.py     中文地名优先                                │
│    charts.py      JMA ASAS/AXFE + 中央气象台天气图             │
│    enso.py        NOAA CPC ONI / BOM SOI                      │
│                                                              │
│  cache/  TTL 缓存（见 §8）                                    │
└──────────────────────────────────────────────────────────────┘
                           │
        DeepSeek / Qwen（OpenAI 兼容，境内，数据不出境）
```

### 为什么拆出 `/api/fact_pack`

地图上的数值和聊天里的解释必须来自**同一份事实**。如果前端自己算一遍、LLM 再从另一条路取一遍，
必然出现「图上 -3 °C，AI 说 -1 °C」，信任一次就崩。所有展示与解释共用一个 fact_pack 实例，
用 `fact_pack_id`（内容哈希）关联日志，可回溯。

---

## 4. Provider 接口

```python
# providers/base.py
from typing import Protocol, Any
from dataclasses import dataclass


@dataclass(frozen=True)
class Sourced:
    """带出处的数值——全项目唯一允许跨层传递的数值容器。"""

    value: float | str | None
    unit: str
    source: str  # "METAR ZBXH" / "Open-Meteo ecmwf_ifs025"
    source_url: str
    valid_time: str  # ISO8601，数据本身的有效时刻
    fetched_at: str  # ISO8601，我们抓取的时刻
    stale_seconds: int = 0  # 允许的过期容忍；超过则在 UI 标灰


class Provider(Protocol):
    name: str

    async def available(self) -> bool: ...
    async def fetch(self, lat: float, lon: float, **kw) -> dict[str, Any]: ...
```

**硬规则**：

- Provider **不得**抛异常出界，失败返回 `{"error": "...", "provider": name}`，由 `fact_pack` 记进 `provenance.missing`。
- Provider **不得**做单位换算，换算统一在 `core/units.py`（旧仓库把英制写死在请求参数里，是必须改掉的债）。
- Provider **不得**调用 LLM。

---

## 5. fact_pack 契约（核心交付物）

```jsonc
{
  "schema_version": "1.0",
  "fact_pack_id": "sha256:9f3a…",          // 内容哈希，用于日志关联
  "generated_at": "2026-11-15T16:30:00+08:00",

  "location": {
    "query": "明安图镇",
    "name": "明安图镇",
    "admin": "内蒙古自治区 锡林郭勒盟 正镶白旗",
    "lat": 42.36, "lon": 115.00,
    "elevation_m": 1350,
    "timezone": "Asia/Shanghai",
    "geocode_source": "qweather",
    "geocode_confidence": 0.9,
    "geocode_candidates": [                    // 有歧义时全部带上，前端可让用户选
      {"name": "明安图镇, 正镶白旗", "lat": 42.36, "lon": 115.00, "score": 0.9}
    ]
  },

  "observed": {                                // ← 观测事实
    "available": true,
    "station": {"id": "ZBXH", "name": "锡林浩特", "distance_km": 150, "elevation_m": 1010},
    "valid_time": "2026-11-15T15:00:00+08:00",
    "age_minutes": 18,
    "temp_c": -3.2,
    "dewpoint_c": -12.0,
    "rh_pct": 50,
    "pressure_msl_hpa": 1032.1,
    "pressure_trend_3h_hpa": 2.1,
    "wind_dir_deg": 320,
    "wind_speed_ms": 8.5,
    "wind_gust_ms": 13.0,
    "cloud_layers": [{"cover": "FEW", "base_m": 1500}],
    "visibility_m": 20000,
    "weather_code": "-SN",
    "source": "METAR",
    "source_url": "https://aviationweather.gov/api/data/metar?ids=ZBXH",
    "representativeness": {
      "level": "低",
      "reason": "最近可用站点在 150 km 外，海拔差 340 m，不能代表明安图镇局地实况"
    }
  },

  "trend_24h": {                               // ← 由 observed 历史序列算出
    "temp_change_c": -6.1,
    "pressure_change_hpa": 3.2,
    "wind_dir_change_deg": -40,
    "basis": "METAR 近 24h 序列"
  },

  "forecast": {                                // ← 模式预报 + 离散度
    "models": ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_global"],
    "daily": [
      {
        "date": "2026-11-16",
        "temp_max": {"mean": 1.2, "p10": -1.0, "p90": 3.4, "spread": 4.4},
        "temp_min": {"mean": -11.5, "p10": -14.2, "p90": -9.0, "spread": 5.2},
        "precip_mm": {"mean": 0.0, "p90": 0.4, "spread": 0.4},
        "wind_max_ms": {"mean": 11.0, "p90": 14.0, "spread": 3.0}
      }
    ],
    "agreement": {
      "temperature_max": {"level": "中", "spread": 4.4},
      "precipitation":   {"level": "高", "spread": 0.4},
      "wind":            {"level": "中", "spread": 3.0}
    }
  },

  "synoptic": {                                // ← 成因解释所需的环流背景
    "h500_geopotential_m": 5320,
    "h500_anomaly_m": -110,
    "t850_c": -8,
    "wind850_dir_deg": 300,
    "wind850_speed_ms": 14,
    "pattern": {
      "label": "高空槽后西北气流控制",
      "confidence": "推断",
      "basis": ["synoptic.h500_anomaly_m < 0", "synoptic.wind850_dir_deg ≈ 300"]
    },
    "charts": [
      {"title": "JMA 亚洲地面天气图 ASAS", "url": "https://www.jma.go.jp/…",
       "valid_time": "2026-11-15T12:00:00+08:00", "license": "JMA 政府标准利用规约"},
      {"title": "JMA 500hPa 高空图", "url": "https://www.jma.go.jp/…",
       "valid_time": "2026-11-15T08:00:00+08:00", "license": "JMA 政府标准利用规约"}
    ]
  },

  "climate": {                                 // ← 气候背景，回答「今年正常吗」
    "season": "初冬",
    "enso": {"phase": "La Niña", "oni": -0.6, "month": "2026-10", "source": "NOAA CPC"},
    "climate_normal": {"temp_max_c": 0.5, "source": "ERA5 30 年均值"}
  },

  "warnings": [                                // ← 官方预警，原文完整搬运
    {
      "title": "大风蓝色预警信号",
      "level": "蓝色",
      "issuer": "正镶白旗气象台",
      "issued_at": "2026-11-15T11:00:00+08:00",
      "text": "正镶白旗气象台2026年11月15日11时00分发布大风蓝色预警信号：…",
      "source_url": "https://…",
      "policy": "原样传播，禁止改写"
    }
  ],

  "provenance": {
    "providers": [
      {"name": "qweather",  "ok": true,  "latency_ms": 320},
      {"name": "open_meteo", "ok": true, "latency_ms": 810},
      {"name": "metar",     "ok": true,  "latency_ms": 240},
      {"name": "enso",      "ok": false, "error": "HTTP 502"}
    ],
    "missing": ["本地实况（最近站 150 km）", "ENSO 指数（源不可用）"],
    "notes": ["METAR 代表性受限，解释层必须声明"]
  }
}
```

**约定**：

- 缺失字段一律 `null` + 进 `provenance.missing`，**不得**用默认值填补。
- 所有时间 ISO 8601 带时区，统一转 `Asia/Shanghai`。
- 所有单位公制（°C / mm / m·s⁻¹ / hPa / m）。
- `synoptic.pattern.confidence` 只能是 `观测` / `预报` / `推断` 三者之一。

---

## 6. 解释层（core/explain.py）

**单次调用，不做 agent 循环。** 便宜模型的 tool-calling 稳定性不足以支撑多轮自主取数，而且取数路径本来就是确定的。

```python
resp = client.chat.completions.create(
    model="deepseek-chat",  # 或 qwen-plus，走 OpenAI 兼容
    temperature=0.3,  # 低温度，减少发挥
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(fact_pack, ensure_ascii=False)},
    ],
)
```

### 输出契约

```jsonc
{
  "headline": "冷高压控制下的晴冷大风天，夜间辐射降温强",
  "facts": [
    {"label": "现在气温", "value": "-3.2 °C", "ref": "observed.temp_c"},
    {"label": "海平面气压", "value": "1032.1 hPa", "ref": "observed.pressure_msl_hpa"},
    {"label": "850hPa 风速", "value": "14 m/s 西北风", "ref": "synoptic.wind850_dir_deg"}
  ],
  "observed":  "…（只陈述 observed 里的内容）",
  "forecast":  "…（只陈述 forecast，注明四模式离散度）",
  "inference": {
    "text": "蒙古冷高压东移南下，槽后西北气流带来干冷空气，加上海拔 1350 m 的辐射冷却…",
    "confidence": "中",
    "basis": ["synoptic.h500_anomaly_m", "synoptic.wind850_dir_deg", "location.elevation_m"]
  },
  "uncertainty": "最高气温四模式差 4.4 °C，主要分歧在云量；降水各模式一致认为无。",
  "advice": "…（生活建议，不是预报结论）",
  "not_covered": ["本地实况（最近站 150 km）"],
  "citations": ["https://aviationweather.gov/…", "https://www.jma.go.jp/…"]
}
```

### System prompt 硬约束（直接可用）

```
你是天气数据解释者，不是预报发布者。

规则：
1. 只能使用输入 JSON（fact_pack）中的数值。任何未出现的数值，一律写“缺”，禁止推测或补全。
2. facts 中每一条都必须带 ref 字段，ref 必须是 fact_pack 中真实存在的路径。
3. 分四段输出：observed（观测事实）、forecast（模式预报）、inference（成因推断）、
   uncertainty（不确定性）。inference 必须提供 basis 数组，指向支撑它的 fact_pack 路径。
4. inference.confidence 只能是 低/中/高，并在 text 里说明哪一环最不确定。
5. 禁止出现“我们预报”“预计将发布”等发布者口吻；只能表述为“XX 台 X 时发布”“四模式显示”。
6. warnings 数组中的 text 必须原样引用，不得改写、不得截断、不得合并。
7. observed.representativeness.level 为“低”时，必须在开头声明观测的代表性局限。
8. 输出必须是合法 JSON，不要 markdown 代码块。
```

### 降级路径

`fact_pack` 组装成功但 LLM 不可用（超时/限流/欠费）时，走 `core/template.py` 的模板填空，
输出「事实罗列 + 无成因推断」版本，并在 UI 明确提示「本次未生成解释」。**宁可少说，不可乱说。**

---

## 7. 数据源清单

| 源 | 用途 | 授权/费用 | 限流 | 失败降级 |
|---|---|---|---|---|
| Open-Meteo（forecast + ensemble） | 多模式预报、**离散度唯一来源** | 免费非商用，免密钥 | 建议自限 10 req/min | 用缓存；缺 spread 则 `agreement=null` |
| 和风天气 QWeather | 中国区要素、公里级格点、官方预警 | 免费额度仅开发，商用需套餐 | 按套餐 | 回退 Open-Meteo |
| METAR（aviationweather.gov） | 最近机场实况 | 免费免密钥 | 每小时更新 | `observed.available=false` |
| JMA ASAS / 高空图 | 成因解释、天气图展示 | 政府标准利用规约，**须署名** | 低频抓取，3h 一次 | 隐藏图表区 |
| 中央气象台公开产品 | 国内天气图、预警 | 公开展示，署名+外链 | 低频 | 同上 |
| NASA GIBS | 云图瓦片 | 免费免密钥，须署名 | 前端直接请求 | 图层开关灰化 |
| 天地图 | 底图 | 免费 key，已过国家地图审核 | 按 key | 降级为纯色底图 |
| NOAA CPC/PSL | ONI / SOI | 公有领域 | 日频 | `climate.enso=null` |
| data.cma.cn | 站点历史、气候态 | 免费注册，**非商用**，见 §9 | 按协议 | 缺失则跳过气候对比 |

---

## 8. 缓存与可靠性

| 数据 | TTL | 理由 |
|---|---|---|
| 地理编码 | 30 天 | 几乎不变 |
| METAR | 10 min | 半小时/小时更新 |
| 预报 | 1 h | 模式 6 h 一更新 |
| 500/850hPa | 3 h | 同上 |
| 天气图 | 3 h | 官方 6 h 一更新 |
| ENSO | 7 天 | 月频 |
| fact_pack | 15 min（按 location 哈希） | 平衡新鲜度与请求数 |

其他：

- 所有外部请求 `timeout=10s`，`tenacity` 重试 2 次（指数退避），仍失败则记录进 `provenance.missing`。
- 并发取数用 `asyncio.gather`，整体超时 20 s，超时的 provider 直接判失败，不阻塞整体。
- 日志：每次请求打印 `fact_pack_id`、各 provider 耗时与状态、LLM token 用量、总耗时。
- LLM 侧：`max_tokens=2000`，输出 JSON 校验失败时重试 1 次（附带校验错误信息），仍失败走模板。

---

## 9. 合规与免责（个人非商用版）

**必须遵守的三条（与是否商用无关）：**

1. **预警与官方预报原样传播**。26 号令第九条：须使用当地气象台最新预报、注明台站名称和发布时间、
   **不得自行更改内容和结论**；第十四条罚则最高 3 万元。实现上：`warnings[].text` 原样渲染，
   AI 的解读必须与其分栏显示，物理上不可混淆。
2. **不得向境外提供从 data.cma.cn 获取的资料**。该条款不区分是否商用。既然 LLM 用境内 DeepSeek/Qwen，
   天然满足；**将来若要接境外模型，必须让 data.cma.cn 来源的字段不出境**（在 provider 层打 `origin` 标记，
   出境模型调用前剥离）。
3. **地图须有审图号**。底图用天地图（已通过国家地图审核），App 内标识其审图号；不使用需要 GCJ-02 纠偏的
   商业瓦片（高德/腾讯/百度）与国际 WGS-84 瓦片混搭。

**个人非商用可以放宽的：**

- data.cma.cn 会员数据可用于非经营性用途，但**仍不得再分发**——所以仅限本地缓存、不对外提供原始数据接口。
- 不需要测绘资质（天地图已审图）。

**UI 免责文案（可直接用）：**

> 本工具为个人天气数据可视化与解释工具，不发布天气预报。
> 要素数据来自 Open-Meteo / 和风天气，实况来自 METAR，天气图来自 JMA / 中央气象台，
> 预警信息以官方发布为准并原样展示。成因解释为基于上述数据的推断，不构成预报结论。

---

## 10. 里程碑与验收

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **M0** | 建仓、目录、settings、CI（ruff+pytest） | `uv run pytest` 绿；`python -m skylens` 打印版本 |
| **M1** | provider 层 + Open-Meteo + METAR + 中文地理编码 | CLI `skylens pack "明安图镇"` 打印完整 fact_pack JSON |
| **M2** | 统计 + synoptic + 天气图 URL + ENSO | fact_pack 中 `forecast.agreement` 与 `synoptic.pattern` 非空 |
| **M3** | explain 层 + 模板降级 + 引用校验 | CLI `skylens explain "明安图镇"` 输出合法 JSON，`facts[].ref` 全部可在 fact_pack 中解析 |
| **M4** | FastAPI + 前端单页（地图+聊天+天气图+外链） | 浏览器打开能看云图、能问问题、引用可点 |
| **M5** | Capacitor 打包 | Android 能装、能显示地图、能对话 |
| **M6** | 回归问题集（10 个明安图/锡林浩特/二连浩特问题） | 每个回答 `not_covered` 与 `basis` 合理，无编造数值 |

**M3 的引用校验是自动化测试的重点**：写一个 `assert_refs_resolvable(answer, fact_pack)`，
遍历 `answer.facts[].ref` 和 `answer.inference.basis[]`，全部必须能在 fact_pack 中取到值。
这条过了，幻觉问题就压住了一大半。

---

## 11. 风险

| 风险 | 影响 | 对策 |
|---|---|---|
| 小镇实况代表性差 | 「现在天气」不准 | UI 强制显示站点距离与海拔差；解释层必须声明 |
| 便宜模型不看指令 | 编造数值 | `ref` 校验 + JSON schema + 重试；失败走模板 |
| 国内 API 条款变动 | 功能下架 | provider 抽象 + 多源回退 |
| 天气图抓取受 ToS 限制 | 无图 | 改为纯外链，不缓存图片 |
| 坐标系统混用 | 位置偏移 | 全项目 WGS-84/CGCS2000，禁 GCJ-02 |

---

## 12. 附录：期望输出形态（M4 之后）

用户问：「帮我解释明安图镇现在的天气及其成因」

```
┌─ 天镜 ─────────────────────────────────────────────┐
│ ⚠ 观测代表性有限：实况来自 150 km 外的锡林浩特机场   │
│ ──────────────── 观测（METAR 15:00）─────────────── │
│ -3.2 °C ▸  露点 -12.0 °C  湿度 50%  气压 1032.1 hPa│
│ 西北风 8.5 m/s（阵风 13.0）  云量少  能见度 20 km    │
│ ──────────────── 预报（4 模式，明日）────────────── │
│ 最高 1.2 °C（-1.0 ~ 3.4，差 4.4）  最低 -11.5 °C    │
│ 降水：各模式一致认为无                               │
│ ──────────────── 推断（依据 500hPa / 850hPa）─────── │
│ 蒙古冷高压东移南下，槽后西北气流输送干冷空气…        │
│ 置信度：中（分歧主要在云量）                         │
│ ──────────────── 图 ────────────────────────────── │
│ [JMA 地面图] [500hPa] [GIBS 云图] [meteoblue ↗]     │
│ ⓘ 数据来源：Open-Meteo / METAR / JMA / 和风天气      │
└────────────────────────────────────────────────────┘
```
