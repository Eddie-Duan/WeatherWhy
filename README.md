# 天镜 SkyLens

> 个人天气数据可视化与解释工具：多源预报 + 云图 + 天气图 + **带出处、分层次、说得出原因**的解释。

给定一个地点，SkyLens 把多源天气数据、卫星云图、天气图与环流形势聚合成一份确定性的
**事实包（fact_pack）**，再由 LLM 把这份事实翻译成人话——每个数字都能点回原始来源。

| 项 | 值 |
|---|---|
| 中文名 / 英文名 | 天镜 / SkyLens |
| 形态 | Web 优先 → Capacitor 套壳出 App |
| 技术栈 | Python 3.12+（FastAPI + httpx）、TypeScript（Vite + MapLibre） |
| LLM | DeepSeek / Qwen，OpenAI 兼容接口，key 只在服务端 |
| 用途 | **个人非商用**：不收费、不对外分发数据、不发布自制预报 |

当前进度：**M0 已完成**（仓库骨架、配置层、CLI 壳、集合统计、CI）。路线图见 [里程碑](#里程碑)。

---

## 它做什么

- **事实与解释分离**：`fact_pack` 由确定性 Python 代码组装，不经 LLM；LLM 只负责把已有事实写成人话。
- **每个数字带 provenance**：`{value, unit, source, source_url, valid_time, fetched_at}` 是数据的最小单元。
- **三层信息强制区分**：观测（observed）/ 预报（forecast）/ 推断（inference），UI 配色不同。
- **多模式离散度**：用 Open-Meteo ensemble 的成员级数据算真实 spread，而不是拿几个模式均值假装一致。
- **官方文案只搬运不改写**：预警原文完整并列展示，AI 只做「这是什么意思、我该怎么办」的解读。

## 它不做什么

| 非目标 | 原因 |
|---|---|
| 发布自制天气预报数值 | 《气象预报发布与传播管理办法》统一发布制度 |
| 改写官方预警文案 | 26 号令第九条：不得自行更改内容和结论 |
| 全国全量覆盖 | 个人项目，先做透 1–3 个地点 |
| 实时高并发 | 单用户场景，不做水平扩展 |
| 自研数值预报 | 数据源够用，自研没有收益 |

成功标准（一句话）：对「明安图镇现在的天气及其成因」这个提问，能给出①带时效和来源的实况
②多模式预报一致性 ③基于 500hPa/850hPa 与天气图的成因推断 ④明确标注哪些是观测、哪些是预报、
哪些是推断 ⑤每个数字可点回原始来源。

---

## 快速开始

需要 Python ≥ 3.12，推荐用 [uv](https://docs.astral.sh/uv/) 管理环境。

```bash
git clone git@github.com:Eddie-Duan/WeatherWhy.git
cd WeatherWhy
uv sync --all-extras          # 建 .venv 并装齐运行 + dev 依赖

cp .env.example .env          # 填 SKYLENS_LLM_API_KEY（其余 key 可选）
uv run skylens --help
uv run skylens sources        # 看各数据源授权形态与本机配置状态
uv run python -m skylens      # 打印版本
```

不用 uv 也可以：

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows；POSIX 用 .venv/bin/activate
pip install -e ".[dev]"
python -m skylens
```

### 当前可用命令（M0）

| 命令 | 作用 |
|---|---|
| `skylens version` | 打印版本 |
| `skylens sources` | 列出数据源、授权形态、本地是否已配 key |
| `skylens configure` | 交互式或 `--llm-api-key/--qweather-key/--tianditu-key` 写密钥进 `.env`（0600） |

`where` / `pack` / `explain` / `serve` / `ask` 按里程碑逐个落地（M1–M4），不提供「假实现」。

---

## 里程碑

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **M0** ✅ | 建仓、目录、settings、CI（ruff + pytest） | `uv run pytest` 绿；`python -m skylens` 打印版本 |
| **M1** | provider 层 + Open-Meteo + METAR + 中文地理编码 | `skylens pack "明安图镇"` 打印完整 fact_pack JSON |
| **M2** | 统计 + synoptic + 天气图 URL + ENSO | `forecast.agreement` 与 `synoptic.pattern` 非空 |
| **M3** | explain 层 + 模板降级 + 引用校验 | `facts[].ref` 全部可在 fact_pack 中解析 |
| **M4** | FastAPI + 前端单页（地图 + 聊天 + 天气图） | 浏览器能看云图、能提问、引用可点 |
| **M5** | Capacitor 打包 | Android 真机能装、能显示地图、能对话 |
| **M6** | 回归问题集（10 个明安图/锡林浩特/二连浩特问题） | `not_covered` 与 `basis` 合理，无编造数值 |

---

## 目录结构

```text
.
├── docs/
│   ├── TECHNICAL_DESIGN.md   # 技术说明：架构、fact_pack 契约、解释层、合规
│   ├── MIGRATION.md          # 从 weather-ensemble-agent 迁移的逐文件处置与步骤
│   └── DATA_SOURCES.md       # 各数据源的授权与署名要求（合规留痕）
├── src/skylens/
│   ├── __init__.py           # 版本号
│   ├── __main__.py           # python -m skylens
│   ├── settings.py           # pydantic-settings 配置层
│   ├── cli.py                # cyclopts + rich 命令行
│   ├── core/                 # 确定性核心：统计、单位、文案（不调 LLM）
│   │   ├── stats.py          # ← 从旧仓 statistics.py 迁移
│   │   ├── units.py          # 单位换算唯一入口
│   │   └── vocab.py          # 中文术语与分级阈值表
│   ├── providers/
│   │   └── base.py           # Sourced + Provider Protocol（数据契约）
│   ├── api/                  # FastAPI（M4）
│   └── cache/                # TTL 缓存（M1）
└── tests/                    # pytest：统计、单位、配置、CLI 冒烟
```

`core/fact_pack.py`、`core/explain.py`、`core/validate.py`、各 provider 在 M1–M3 补上。
完整设计与取舍见 [docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md)。

---

## 数据源与署名

要素与预报来自 **Open-Meteo**（含 ensemble）与 **和风天气**；实况来自 **METAR**
（aviationweather.gov）；天气图来自 **JMA** 与 **中央气象台**；云图瓦片来自 **NASA GIBS**；
底图为 **天地图**（已通过国家地图审核，App 内标识审图号）；ENSO 指数来自 **NOAA CPC**。

各源的授权、署名要求与限制见 [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)。

---

## 免责声明与合规

> 本工具为个人天气数据可视化与解释工具，**不发布天气预报**。
> 要素数据来自 Open-Meteo / 和风天气，实况来自 METAR，天气图来自 JMA / 中央气象台，
> 预警信息以官方发布为准并原样展示。成因解释为基于上述数据的推断，不构成预报结论。

与是否商用无关的三条硬约束（实现层面强制）：

1. **预警与官方预报原样传播**：注明台站名称与发布时间，不得更改内容和结论；AI 解读与原文分栏显示。
2. **不得向境外提供从 data.cma.cn 获取的资料**：LLM 只用境内模型；将来接境外模型时须按 `origin` 标记剥离。
3. **地图须有审图号**：底图用天地图；全项目 WGS-84/CGCS2000，禁止 GCJ-02 纠偏与混搭。

---

## 开发

```bash
uv run ruff check .          # lint
uv run ruff format .         # 格式化
uv run pytest                # 全量测试
pre-commit install           # 可选：提交前自动跑 ruff + pytest
```

CI（GitHub Actions）在每次 push 到 `main` 和每个 PR 上跑 ruff check、ruff format --check、pytest。

---

## 许可

代码以 [MIT](LICENSE) 发布。项目本身非商用；第三方数据的授权以其各自条款为准。
