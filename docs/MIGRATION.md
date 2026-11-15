# 从 weather-ensemble-agent 迁移到 天镜 SkyLens

> 目标：把旧仓库里**值得留的 30%** 搬进新仓，其余按 §5 的步骤重写。
> 结论先说：旧仓的 `agent.py` 循环可以直接扔，`statistics.py` 是唯一的真金，`weather_api.py` 必须拆。

---

## 1. 迁移总览

| 类别 | 占比 | 文件 |
|---|---|---|
| ✅ 直接搬（改 import / 改类型） | ~25% | `tools/statistics.py`、`config.py`、`cli.py` 的壳 |
| 🔧 重写 | ~50% | `tools/weather_api.py`、`tools/geocoding.py`、`agent.py` 的 prompt 与输出层 |
| 🗑 丢弃 | ~25% | `main.py`、`examples/`、`visualization/plotter.py`、`agent.py` 的 10 轮循环、`REVIEW_FEEDBACK.md` |

**行业经验值**：旧仓 1 913 行 Python，新仓预计 2 500–3 000 行（不含前端），
其中约 500 行从旧仓搬运，其余新写。业余节奏 **1.5–2 周** 到 M4。

---

## 2. 逐文件处置

### 2.1 ✅ `src/weather_agent/tools/statistics.py`（356 行）→ `skylens/core/stats.py`

**这是旧仓最有价值的文件，算法全部保留。**

| 函数 | 处置 | 说明 |
|---|---|---|
| `calculate_ensemble_statistics` | 保留 | 唯一改动：输入从「分模式数组」改为「ensemble 成员数组」，`use_max` 参数保留 |
| `calculate_model_agreement` | 保留 | 阈值（spread <3 / <7）直接沿用，但改成返回 `{"level","spread"}` 结构 |
| `summarize_forecast_uncertainty` | 保留 | 同上，输出对齐 fact_pack 的 `forecast.agreement` |
| `calculate_daily_temperature_range_statistics` | 保留 | 可选，用于日较差分析 |
| `_is_daily_data` / `_extract_variable_data` | 保留 | 内部工具函数原样搬 |

**唯一必改项**：`_is_daily_data` 靠猜字段名（`temperature_max` 存在即为日数据）。
新仓的 fact_pack 结构是确定的，应改为显式参数 `kind="daily"|"hourly"`，删掉这个猜测逻辑。

### 2.2 🔧 `src/weather_agent/tools/weather_api.py`（261 行）→ `skylens/providers/open_meteo.py` + `providers/metar.py`

**不能直接搬**，三个硬伤：

| 硬伤 | 位置 | 新仓做法 |
|---|---|---|
| 只请求 3 个变量（temp/precip/wind） | `weather_api.py:131` | 按需字段：`current` + `hourly` + `daily` + `pressure_level`（500/850hPa） |
| 英制硬编码 | `weather_api.py:133-135` | 请求用公制，换算集中在 `core/units.py` |
| endpoint 硬编码在函数体内 | `weather_api.py:101-106`、`259-264` | 抽成 `ModelRegistry` 配置，可配置、可增删 |
| 无 `current` / `past_days` | 全文 | 加 `current=…&past_days=2`，供实况与 24h 趋势 |
| 串行 for 循环 | `weather_api.py:114` | `asyncio.gather` 并发，单源失败不阻塞 |
| 原始数组直接返回 | 全文 | 返回 `Sourced` 包装，带 `source/source_url/valid_time` |

**新仓需要新增的两个函数**：

```python
async def fetch_ensemble(lat, lon, models: list[str], days: int) -> dict
    # 用 ensemble-api.open-meteo.com，拿成员级数据 → 才能算真实 spread
async def fetch_pressure_levels(lat, lon, levels=(500, 850)) -> dict
    # hourly=temperature_500hPa,geopotential_height_500hPa,
    #        wind_speed_850hPa,wind_direction_850hPa,…
```

**METAR 是全新模块**（旧仓没有），这是「现在天气」的正解：

```python
# providers/metar.py
async def fetch_nearest(lat, lon, radius_km=300) -> dict:
    # 1. 找最近站：aviationweather.gov 的 stationinfo 或内置站点表
    # 2. GET https://aviationweather.gov/api/data/metar?ids=ZBXH&format=json
    # 3. 解析：温度/露点/气压(QNH)/风向风速/阵风/云层/能见度/天气现象
    # 4. 附 representativeness：距离 + 海拔差 → "低/中/高"
```

### 2.3 🔧 `src/weather_agent/tools/geocoding.py`（27 行）→ `skylens/providers/geocode.py`

**必须换源**。Nominatim `limit=1` 对中文小镇太弱：

```python
# 现状：geocoding.py:17-19
url = "https://nominatim.openstreetmap.org/search"
params = {"q": location, "format": "json", "limit": 1}
```

新仓：

1. 主源：和风天气 GeoAPI（中文地址命中率高，`lang=zh`）
2. 备源：Open-Meteo geocoding（拼音/英文）
3. 兜底：Nominatim（欧美地名）
4. **`limit` 提到 5**，全部返回 `location.geocode_candidates`，让用户/模型选；`geocode_confidence` 取首条得分

### 2.4 🔧 `src/weather_agent/agent.py`（555 行）→ `skylens/core/explain.py`

**旧仓的核心问题：它是个「让模型自己找数据」的 agent；新仓要「数据先齐，模型只解释」。**

| 旧代码 | 处置 | 理由 |
|---|---|---|
| `run()` 的 10 轮 `while` 循环（`agent.py:434-527`） | 🗑 删 | 便宜模型多轮调用不稳定；取数路径是确定的，不需要模型规划 |
| `_define_tools()`（8 个工具 schema，`agent.py:73-315`） | 🗑 删 | 换成一个结构化输入（fact_pack）+ 一个 JSON 输出契约 |
| `_execute_tool()` 分发表（`agent.py:316-359`） | 🔧 改 | 变成 `fact_pack.py` 里的 provider 编排，不再由模型触发 |
| system prompt（`agent.py:401-426`） | 🔧 重写 | 现版没要求区分观测/预报/推断，是幻觉根源；新版见 TECHNICAL_DESIGN §6 |
| `model="claude-sonnet-4-20250514"`（`agent.py:445`） | 🔧 换 | OpenAI 兼容客户端，模型名走配置 |
| tool_result 回灌（`agent.py:497-503`） | 🗑 删 | 不再有 tool 往返 |
| 打印截断 1 000 字符（`agent.py:490`） | 🗑 删 | 旧逻辑只截显示、不截上下文，等于白截 |

**保留一句旧仓的话**（`agent.py:404-405` 的思路是对的）：把「今天是几号」显式写进 prompt。
新仓还应加「当前时刻 + 数据时刻」，否则模型会把相对时间算错。

### 2.5 🗑 `src/weather_agent/visualization/plotter.py`（252 行）

**不迁移**。理由：新仓的图由前端 MapLibre 直接渲染，服务端 matplotlib 静态图与交互式地图重复。

- 唯一保留场景：调试时快速看点位的时序曲线 → 降级为 `scripts/plot_debug.py`（10 行，随手写）。
- 如果 M3 之前想快速看到东西，可以先把它拷过来当临时验证工具，M4 后删。

### 2.6 ✅ `src/weather_agent/config.py`（63 行）→ `skylens/settings.py`

结构和优先级（env > 配置文件 > 报错）保留，换成 `pydantic-settings`：

```python
class Settings(BaseSettings):
    llm_provider: Literal["deepseek", "qwen"] = "deepseek"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str
    llm_model: str = "deepseek-chat"
    qweather_key: str | None = None
    tianditu_key: str | None = None
    cache_dir: Path = Path.home() / ".cache" / "skylens"
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SKYLENS_")
```

旧的 `save_api_key()` + `chmod(0o600)` 那套保留（`config.py:43-57`），很实用。

### 2.7 ✅ `src/weather_agent/cli.py`（278 行）→ `skylens/cli.py`

**保留壳，改语义**。cyclopts + rich 的用法没问题，但子命令要变：

| 旧子命令 | 新子命令 | 变化 |
|---|---|---|
| `forecast <loc>` | `pack <loc>` | 不再启动 agent，直接打印 fact_pack |
| `compare <loc>` | `explain <loc>` | 输出结构化解释 JSON + 渲染 |
| `visualize <loc>` | `serve` | 起 FastAPI（供前端） |
| `ask <query>` | `ask <query>` | 保留，自由问句入口 |
| `list-models` | `sources` | 改成列 provider 及健康状态 |
| `coordinates <loc>` | `where <loc>` | 保留，多返回候选与置信度 |
| `configure` | `configure` | 保留，加各 provider key |

`cli.py:63-67` 那种「把参数拼成一句自然语言交给 agent」的做法**要删**——这是旧仓最反模式的
设计：参数已经结构化了，再拼回自然语言让模型解析一遍，既浪费 token 又不稳定。

### 2.8 🗑 丢弃清单

| 文件 | 理由 |
|---|---|
| `main.py`（6 行） | 占位 Hello World，无意义 |
| `examples/test_timezone.py`、`examples/test_visualization.py` | 临时脚本，不是测试；新仓建 `tests/` 写真测试 |
| `REVIEW_FEEDBACK.md`（19 KB） | 旧仓评审记录，与新仓无关；**但迁移前值得读一遍**，里面大概率有已被指出的坑 |
| `README.md`（35 KB） | 只取「项目结构」「配置」两节的思路，正文重写 |
| `.pre-commit-config.yaml` | 参考，但 hook 版本要升级 |

---

## 3. 新仓目录结构

```
skylens/
├── README.md                     # 名字 + 一句话 + 截图 + 免责声明
├── LICENSE                       # MIT
├── pyproject.toml
├── .env.example
├── .pre-commit-config.yaml
├── docs/
│   ├── TECHNICAL_DESIGN.md       # ← 本文档的姊妹篇
│   ├── MIGRATION.md              # ← 本文档
│   └── DATA_SOURCES.md           # 每个源的授权/署名要求（合规留痕）
├── src/skylens/
│   ├── __init__.py
│   ├── __main__.py
│   ├── settings.py
│   ├── cli.py
│   ├── core/
│   │   ├── fact_pack.py          # 编排 providers → fact_pack
│   │   ├── stats.py              # ← 从旧仓 statistics.py 搬
│   │   ├── units.py              # 单位换算（新增，旧仓缺）
│   │   ├── vocab.py              # 中文术语/等级文案
│   │   ├── explain.py            # LLM 单次调用
│   │   ├── template.py           # LLM 不可用时的降级
│   │   └── validate.py           # assert_refs_resolvable（核心测试）
│   ├── providers/
│   │   ├── base.py               # Provider Protocol + Sourced
│   │   ├── open_meteo.py         # ← 从旧仓 weather_api.py 重写
│   │   ├── qweather.py
│   │   ├── metar.py              # 新增
│   │   ├── geocode.py            # ← 从旧仓 geocoding.py 重写换源
│   │   ├── charts.py             # 新增：JMA / CMA 天气图
│   │   ├── enso.py               # 新增：NOAA ONI / BOM SOI
│   │   └── registry.py           # 模型注册表（旧仓的硬编码 endpoint 移到这）
│   ├── api/
│   │   ├── main.py               # FastAPI 应用
│   │   └── routes.py
│   ├── cache/
│   │   └── store.py              # TTL 缓存
│   └── prompts/
│       └── explain_v1.txt        # system prompt（可版本化、可 A/B）
├── web/                          # Vite + TS + MapLibre
│   ├── index.html
│   ├── src/
│   │   ├── main.ts
│   │   ├── map.ts                # 天地图底图 + GIBS 叠加
│   │   ├── panels.ts             # 天气图/云图/ENSO 面板
│   │   ├── chat.ts               # SSE 聊天 + 引用渲染
│   │   └── theme.css
│   └── package.json
├── mobile/                       # M5 才建
└── tests/
    ├── test_stats.py             # ← 从旧仓算法反推的用例
    ├── test_fact_pack_schema.py
    ├── test_refs_resolvable.py   # 防幻觉的关键测试
    └── fixtures/
        └── mingantu_pack.json    # 一个真实 fact_pack 快照
```

---

## 4. 依赖变更

```diff
 [project]
 dependencies = [
-    "anthropic>=0.75.0",          # 🗑 换
+    "openai>=1.60",               # ← DeepSeek/Qwen 都走 OpenAI 兼容
     "cyclopts>=4.4.4",            # ✅ 保留
     "matplotlib>=3.10.8",         # 🗑 移到 dev（只在调试脚本用）
     "numpy>=2.4.0",               # ✅ 保留
-    "pydantic>=2.12.5",
+    "pydantic>=2.12.5",
+    "pydantic-settings>=2.7",     # 新增
     "python-dotenv>=1.2.1",       # ✅ 保留
-    "requests>=2.32.5",           # 🔧 保留但只用于少量同步场景
+    "httpx>=0.28",                # 新增：异步 + 超时/重试更可控
+    "tenacity>=9.0",              # 新增：重试
+    "fastapi>=0.115",             # 新增
+    "uvicorn[standard]>=0.34",    # 新增
+    "orjson>=3.10",               # 新增：fact_pack 序列化
 ]
```

dev 组追加：`pytest-asyncio`、`respx`（mock httpx）、`ruff`、`pytest`。

---

## 5. 迁移步骤（每一步都可运行、可验证）

### Step 0 · 建仓（0.5 天）

```bash
mkdir skylens && cd skylens
git init
uv init --package --name skylens
# 手写 pyproject.toml（见 §4）
mkdir -p src/skylens/{core,providers,api,cache,prompts} tests/fixtures docs web
uv sync --all-extras
```

**验收**：`uv run python -c "import skylens; print(skylens.__version__)"` 有输出。

### Step 1 · 搬三块可直接用的（0.5 天）

1. `statistics.py` → `core/stats.py`，改 import、删 `_is_daily_data` 猜测逻辑
2. `config.py` → `settings.py`，套 `pydantic-settings`
3. `cli.py` 的 cyclopts+rich 壳 → `cli.py`，先只留 `where` / `sources` / `configure`

**验收**：`uv run skylens where "明安图镇"` 能打印坐标。

### Step 2 · Provider 层 + Open-Meteo + METAR（1.5 天）

按 `providers/base.py` 的 Protocol 写 `open_meteo.py`、`metar.py`、`geocode.py`。
`registry.py` 承接旧仓的 `model_endpoints`。

**验收**：`uv run skylens pack "明安图镇" --raw` 打印出**符合 §5 契约的完整 JSON**，
且 `observed.temp_c`、`forecast.daily[0].temp_max.spread` 都有值。

### Step 3 · fact_pack 组装 + 统计接入（1 天）

`core/fact_pack.py` 用 `asyncio.gather` 编排，写入 `provenance`。
把 `stats.py` 输出映射到 `forecast.agreement`。

**验收**：`fact_pack` 通过 `tests/test_fact_pack_schema.py`（用 pydantic 模型校验），
缺数据时 `missing` 非空而不是崩。

### Step 4 · explain 层 + 引用校验（1 天）

写 `prompts/explain_v1.txt`，`core/explain.py` 调 LLM，`core/validate.py` 校验。

**验收**：`uv run skylens explain "明安图镇"` 输出合法 JSON；
`assert_refs_resolvable` 通过；故意删掉 fact_pack 里一个字段，测试应报错。

### Step 5 · FastAPI + 前端（2–3 天）

`/api/fact_pack`、`/api/explain`（SSE）、`/api/warnings`、`/api/charts`。
前端：天地图底图 + GIBS 云图图层 + 天气图面板 + 聊天。

**验收**：浏览器打开 → 看到明安图镇位置与云图 → 问一句 → 3–5 秒出带引用的回答 → 引用可点。

### Step 6 · Capacitor（1 天，可选延后）

```bash
cd web && npm i -D @capacitor/cli && npx cap init
npx cap add android
npx cap sync
```
关键：`API_BASE` 改成远端 FastAPI 地址；LLM key 永不下发到客户端。

**验收**：Android 真机能装、能显示地图、能对话。

---

## 6. `.env.example`

```bash
# LLM（OpenAI 兼容）
SKYLENS_LLM_PROVIDER=deepseek
SKYLENS_LLM_BASE_URL=https://api.deepseek.com/v1
SKYLENS_LLM_API_KEY=sk-...
SKYLENS_LLM_MODEL=deepseek-chat
# 备选：qwen
# SKYLENS_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# SKYLENS_LLM_MODEL=qwen-plus

# 国内数据（可选，缺省回退 Open-Meteo）
SKYLENS_QWEATHER_KEY=
SKYLENS_TIANDITU_KEY=

# 运行
SKYLENS_CACHE_DIR=~/.cache/skylens
SKYLENS_LOG_LEVEL=INFO
```

---

## 7. 旧仓技术债清单（迁移时顺手清掉）

| # | 债 | 位置 | 清法 |
|---|---|---|---|
| 1 | 英制单位硬编码 | `weather_api.py:133-135` | 公制 + `core/units.py` |
| 2 | endpoint 硬编码 | `weather_api.py:101-106, 259-264` | `providers/registry.py` |
| 3 | 模型名硬编码 | `agent.py:445` | settings |
| 4 | 无 provenance | 全文 | `Sourced` 包装 |
| 5 | 参数拼回自然语言 | `cli.py:63-67` | 直接传结构体 |
| 6 | 工具返回全量数组 | `weather_api.py` + `agent.py:497` | fact_pack 只给统计值 |
| 7 | `_is_daily_data` 猜结构 | `statistics.py:9` | 显式 `kind` 参数 |
| 8 | 无测试 | 全仓 | `tests/`，重点是引用校验 |
| 9 | 串行取数 | `weather_api.py:114` | `asyncio.gather` |
| 10 | 只截显示不截上下文 | `agent.py:490` | 根本不再传原始数组 |
| 11 | 无缓存 | 全文 | TTL 表（见设计文档 §8） |
| 12 | `conversation_history` 声明未用 | `agent.py:68` | 删；多轮等到确实需要再加 |

---

## 8. 迁移验收 checklist

- [ ] 新仓能 `uv sync` 无冲突
- [ ] `skylens where "明安图镇"` 返回内蒙古正镶白旗的坐标（不是同名异地）
- [ ] `skylens pack "明安图镇"` 产出符合契约的 fact_pack，含 `observed` 与 `forecast.agreement`
- [ ] `observed.representativeness.level` 有值且理由可读
- [ ] `skylens explain` 输出的每个 `facts[].ref` 都能在 fact_pack 中解析
- [ ] 断网时 `skylens explain` 走模板降级，不崩、不编
- [ ] 前端能显示云图瓦片，位置与坐标一致（无 GCJ-02 偏移）
- [ ] 预警区与 AI 解读分栏显示，原文完整可复制
- [ ] `pytest` 全绿，含 `test_refs_resolvable.py`
- [ ] README 含免责声明与数据源署名

---

## 9. 时间估算（业余）

| 阶段 | 天 | 累计 |
|---|---|---|
| M0 建仓 | 0.5 | 0.5 |
| M1 provider + 实况 | 2 | 2.5 |
| M2 fact_pack + 统计 + synoptic | 1.5 | 4 |
| M3 explain + 校验 | 1.5 | 5.5 |
| M4 API + 前端 | 3 | 8.5 |
| M5 Capacitor | 1 | 9.5 |
| M6 回归问题集 | 1 | 10.5 |

**约 10–11 个工作日**到能在手机上用。
若只想先看到东西：**M0→M1→M3 跳过前端（5 天）**，CLI 就能回答「明安图镇现在天气及其成因」——
这已经是旧仓做不到的事，也是这个项目真正的核心价值。
