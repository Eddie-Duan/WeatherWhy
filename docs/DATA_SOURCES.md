# 数据源与署名要求

> 合规留痕：每个外部数据源的授权形态、署名要求、限流与失败降级。
> 与本文件不符的实现视为 bug。总则见 [TECHNICAL_DESIGN.md §9](TECHNICAL_DESIGN.md)。

| 源 | 用途 | 授权 / 费用 | 署名要求 | 限流 | 失败降级 |
|---|---|---|---|---|---|
| [Open-Meteo](https://open-meteo.com/)（forecast + ensemble） | 多模式预报、**离散度唯一来源** | 免费非商用，免密钥 | 需注明数据来源 | 自限 10 req/min | 用缓存；缺 spread 则 `agreement=null` |
| [和风天气 QWeather](https://www.qweather.com/) | 中国区要素、公里级格点、官方预警、中文地名 | 免费额度仅开发，商用需套餐 | 按协议 | 按套餐 | 回退 Open-Meteo |
| [Nominatim](https://nominatim.openstreetmap.org/) | 中文地名（**实测对镇级地名最稳**） | 免费，须带 UA 且不得高频 | 注明 OpenStreetMap 贡献者 | 1 req/s 自限，结果缓存 30 天 | 回退 Open-Meteo geocoding |
| [METAR / aviationweather.gov](https://aviationweather.gov/) | 最近机场实况（真观测） | 免费免密钥 | 注明站点 ICAO | 每小时更新 | `observed.available=false` |
| [JMA](https://www.jma.go.jp/) ASAS / 高空图 | 成因解释、天气图展示 | 政府标准利用规约 | **须署名 JMA** | 低频抓取，3 h 一次 | 隐藏图表区 |
| [中央气象台](http://www.nmc.cn/) 公开产品 | 国内天气图、预警 | 公开展示 | 署名 + 外链 | 低频 | 同上 |
| [NASA GIBS](https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs) | 云图瓦片 | 免费免密钥 | **须署名 NASA GIBS** | 前端直接请求 | 图层开关灰化 |
| [天地图](https://www.tianditu.gov.cn/) | 底图 | 免费 key，已过国家地图审核 | 标识审图号 | 按 key | 降级为纯色底图 |
| [NOAA CPC/PSL](https://www.cpc.ncep.noaa.gov/) | ONI / SOI | 公有领域 | 注明 NOAA CPC | 日频 | `climate.enso=null` |
| [data.cma.cn](http://data.cma.cn/) | 站点历史、气候态 | 免费注册，**非商用** | 按协议 | 按协议 | 缺失则跳过气候对比 |
| [DeepSeek](https://www.deepseek.com/)（备选 Qwen） | 解释层：只接收 fact_pack，产出人话 | 按 token 计费，境内 | 无需额外署名 | 由服务商限流 | 超时/失败 → 模板降级（`degraded: true`） |

## 三条不得越线的地方

1. **预警与官方预报原样传播**（26 号令第九条）：须使用当地气象台最新预报、注明台站名称和发布时间、
   不得自行更改内容和结论；第十四条罚则最高 3 万元。实现上 `warnings[].text` 原样渲染，
   AI 解读与其分栏显示，物理上不可混淆。
2. **data.cma.cn 资料不得向境外提供**：该条款不区分是否商用。当前 LLM 只用境内
   DeepSeek/Qwen；若将来接入境外模型，必须在 provider 层打 `origin` 标记，调用前剥离这些字段。
3. **地图须有审图号**：底图用天地图；全项目统一 WGS-84/CGCS2000，不使用需 GCJ-02 纠偏的
   商业瓦片（高德/腾讯/百度）与国际 WGS-84 瓦片混搭。

## 缓存与再分发

- 所有外部数据仅在本地 TTL 缓存中使用，**不对外提供原始数据接口**（data.cma.cn 尤其）。
- 天气图默认只做外链与缩略图展示，不长期缓存图片（尊重源的 ToS）。

## 实测补充（2026-11-15）

- **Open-Meteo geocoding 对旗县级中文地名返回空**（`明安图`、`明安图镇`、`正镶白旗` 均无结果），
  而 Nominatim 能返回 `明安图镇 → 42.2984, 115.0014（正镶白旗/锡林郭勒盟/内蒙古自治区）`。
  因此 geocode 顺序调整为 QWeather → Nominatim → Open-Meteo，见 `providers/geocode.py` 模块文档。
- **aviationweather.gov 的 METAR 接口在站点稀疏区会返回 204**（无内容而非空数组），
  必须按「无响应」处理；`wdir` 可能是字符串 `VRB`，`visib` 可能是 `"6+"`。
- 单位口径（来自真实响应）：`wspd`/`wgst` 为节、`visib` 为法定英里、`clouds[].base` 为英尺、`altim` 为 hPa。
