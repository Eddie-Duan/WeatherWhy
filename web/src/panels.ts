// 渲染：事实包（要点卡片 + 折叠预警 + 分区）、天气图、解释回答。
// 三层信息用不同标记与配色（观测/预报/推断），官方预警用红色。

import type { Answer, Chart, FactPack, Stat } from "./api";

const esc = (value: unknown): string =>
  String(value ?? "—").replace(/[&<>"']/g, (ch) => {
    const map: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return map[ch] ?? ch;
  });

const num = (value: number | null | undefined, unit = "", digits = 1): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const text = Number.isInteger(value) ? String(value) : value.toFixed(digits);
  return unit ? `${text} ${unit}` : text;
};

const stat = (block: Stat | undefined): string => {
  if (!block || block.mean === null || block.mean === undefined) return "—";
  return `${num(block.mean)}±${num(block.spread)}`;
};

const refSpan = (ref: string, text: string): string =>
  `<span class="ref-target" data-ref="${esc(ref)}">${text}</span>`;

/** 归一化引用路径：`daily[1]` 与 `daily.1` 视为同一条。 */
export const normalizeRef = (ref: string): string => ref.replace(/[[\].]/g, "").toLowerCase();

let lastPack: FactPack | null = null;

/** 在已渲染的事实包里解析路径（支持 a.b[0].c 与 a.b.0.c）。 */
export function resolvePackPath(pack: unknown, ref: string): unknown {
  const tokens = ref
    .replace(/\[(\d+)\]/g, ".$1")
    .split(".")
    .filter(Boolean);
  let current: unknown = pack;
  for (const token of tokens) {
    if (current === null || current === undefined) return undefined;
    if (Array.isArray(current)) {
      const index = Number(token);
      if (!Number.isInteger(index) || index >= current.length) return undefined;
      current = current[index];
    } else if (typeof current === "object") {
      const record = current as Record<string, unknown>;
      if (!(token in record)) return undefined;
      current = record[token];
    } else {
      return undefined;
    }
  }
  return current;
}

export type FocusResult = "dom" | "pack" | "missing";

/** 点引用 → 在事实包里定位并闪一下；面板未展示的字段也会如实区分。 */
export function focusRef(ref: string): FocusResult {
  const target = normalizeRef(ref);
  const nodes = Array.from(document.querySelectorAll<HTMLElement>("#fact-panel [data-ref]"));
  const hit = nodes.find((node) => normalizeRef(node.dataset.ref ?? "") === target);
  if (!hit) {
    return lastPack && resolvePackPath(lastPack, ref) !== undefined ? "pack" : "missing";
  }
  hit.scrollIntoView({ behavior: "smooth", block: "center" });
  hit.classList.remove("flash");
  void hit.offsetWidth;
  hit.classList.add("flash");
  window.setTimeout(() => hit.classList.remove("flash"), 1800);
  return "dom";
}

const AGREEMENT_LABELS: Record<string, string> = {
  temperature_max: "最高气温",
  temperature_min: "最低气温",
  precipitation: "降水",
  wind: "风",
};

const LEVEL_CLASS: Record<string, string> = {
  红色: "lvl-red",
  橙色: "lvl-orange",
  黄色: "lvl-yellow",
  蓝色: "lvl-blue",
  白色: "lvl-white",
  黑色: "lvl-black",
};

function metricCard(
  label: string,
  value: string,
  unit: string,
  tag: string,
  ref: string | null,
  sub = "",
  tagClass = "",
): string {
  const body = `<div class="metric-label">${esc(label)}</div>
    <div class="metric-value">${ref ? refSpan(ref, esc(value)) : esc(value)}${
      unit ? `<span class="metric-unit">${esc(unit)}</span>` : ""
    }</div>
    ${sub ? `<div class="metric-sub">${esc(sub)}</div>` : ""}`;
  return `<div class="metric"><span class="tag ${tagClass}">${esc(tag)}</span>${body}</div>`;
}

export function renderFact(container: HTMLElement, pack: FactPack): void {
  lastPack = pack;
  const location = pack.location;
  const observed = pack.observed;
  const forecast = pack.forecast;
  const synoptic = pack.synoptic;
  const climate = pack.climate;
  const rep = observed.representativeness;
  const today = (forecast?.daily ?? [])[0];
  const warnings = pack.warnings ?? [];
  const missing = pack.provenance.missing ?? [];

  // ---- 要点卡片：一眼看到今天该关心的数字 ----
  const metrics: string[] = [];
  const local = observed.local;
  if (local && local.temp_c !== null && local.temp_c !== undefined) {
    metrics.push(
      metricCard(
        "本地实况",
        num(local.temp_c),
        "°C",
        "实况",
        "observed.local.temp_c",
        `和风格点 · ${local.weather_text ?? ""} · 体感 ${num(local.feels_like_c, "°C")}`,
        "tag-observed",
      ),
    );
  }
  const stationKm = observed.station?.distance_km ?? null;
  if (observed.available && (stationKm === null || stationKm <= 100)) {
    metrics.push(
      metricCard(
        "机场站点",
        num(observed.temp_c),
        "°C",
        "观站",
        "observed.temp_c",
        `${observed.station?.id ?? ""} · ${num(stationKm, "km", 0)} 外`,
        "tag-observed",
      ),
    );
  }
  if (today) {
    metrics.push(
      metricCard("今日最高", num(today.temp_max?.mean), "°C", "预报",
        "forecast.daily.0.temp_max.mean", `±${num(today.temp_max?.spread)}`, "tag-forecast"),
      metricCard("今日最低", num(today.temp_min?.mean), "°C", "预报",
        "forecast.daily.0.temp_min.mean", `±${num(today.temp_min?.spread)}`, "tag-forecast"),
      metricCard("降水", num(today.precip_mm?.mean), "mm", "预报",
        "forecast.daily.0.precip_mm.mean", `一致性 ${esc(
          forecast?.agreement?.precipitation?.level ?? "缺",
        )}`, "tag-forecast"),
      metricCard("最大风", num(today.wind_max_ms?.mean), "m/s", "预报",
        "forecast.daily.0.wind_max_ms.mean", `±${num(today.wind_max_ms?.spread)}`, "tag-forecast"),
    );
  }
  metrics.push(
    metricCard(
      "官方预警",
      String(warnings.length),
      "条",
      "官方",
      "warnings",
      warnings.length ? esc(warnings[0]?.issuer ?? "") : "当前无生效预警",
      "tag-danger",
    ),
  );

  // ---- 预警：默认折叠，展开才是原文（原文一字不改） ----
  const warningsBlock = warnings.length
    ? `<section class="section" data-ref="warnings">
        <h3>官方预警 <span class="count">${warnings.length}</span></h3>
        <p class="hint">以下为官方发布原文，未做任何改写；点击标题展开全文。</p>
        ${warnings
          .map((item) => {
            const levelClass = LEVEL_CLASS[String(item.level ?? "")] ?? "";
            return `<details class="warning ${levelClass}">
              <summary>
                <span class="warning-level">${esc(item.level ?? "预警")}</span>
                <span class="warning-title">${esc(item.title)}</span>
                <span class="warning-meta">${esc(item.issuer)} · ${esc(
                  (item.issued_at ?? "").replace("T", " ").slice(0, 16),
                )}</span>
              </summary>
              <div class="warning-body">
                <p class="warning-text">${esc(item.text)}</p>
                ${item.advice ? `<p class="warning-advice">防御指南：${esc(item.advice)}</p>` : ""}
                <p class="warning-source">来源：${esc(item.attribution ?? "官方气象部门")}${
                  item.source_url
                    ? ` · <a href="${esc(item.source_url)}" target="_blank" rel="noreferrer noopener">接口</a>`
                    : ""
                }<button type="button" class="copy-btn" data-copy="${esc(item.text)}">复制原文</button></p>
              </div>
            </details>`;
          })
          .join("")}
      </section>`
    : "";

  // ---- 观测 ----
  const localBlock = local
    ? `<div class="local-now">
        <div class="local-now-title">本地实况 <span class="tag tag-observed">格点</span>
          <span class="hint-inline">${esc(local.kind)} · ${esc(
            (local.valid_time ?? "").replace("T", " ").slice(5, 16),
          )}</span></div>
        <div class="metrics compact">
          ${metricCard("气温", num(local.temp_c), "°C", "实况", "observed.local.temp_c", "", "tag-observed")}
          ${metricCard("体感", num(local.feels_like_c), "°C", "实况", "observed.local.feels_like_c", "和风算法", "tag-observed")}
          ${metricCard("风", num(local.wind_speed_ms), "m/s", "实况", "observed.local.wind_speed_ms",
            `${num(local.wind_dir_deg, "°")}`, "tag-observed")}
        </div>
        <p class="hint">${esc(local.source ?? "")}${
          local.weather_text ? ` · 现象 ${esc(local.weather_text)}` : ""
        }</p>
      </div>`
    : "";

  const stationDetail = observed.available
    ? `<details class="notes station-detail" ${stationKm !== null && stationKm > 100 ? "" : "open"}>
        <summary>机场站点观测 ${esc(observed.station?.id ?? "")} · ${num(
          stationKm,
          "km",
          0,
        )} 外${stationKm !== null && stationKm > 100 ? "（仅作参考，不代表本地）" : ""}</summary>
        <div class="warn ${rep && rep.level === "低" ? "degraded" : ""}">
          代表性 <strong>${esc(rep?.level ?? "未知")}</strong>：${esc(rep?.reason ?? "")}
        </div>
        <dl class="kv">
          <dt>气温</dt><dd>${refSpan("observed.temp_c", num(observed.temp_c, "°C"))}</dd>
          ${
            observed.temp_adjusted
              ? `<dt>海拔订正</dt><dd>${refSpan(
                  "observed.temp_adjusted.temp_c",
                  num(observed.temp_adjusted.temp_c, "°C"),
                )} <span class="hint-inline">自算，按 ${num(
                  observed.temp_adjusted.lapse_rate_c_per_km,
                  "°C/km",
                )}</span></dd>`
              : ""
          }
          <dt>露点</dt><dd>${refSpan("observed.dewpoint_c", num(observed.dewpoint_c, "°C"))}</dd>
          <dt>湿度</dt><dd>${refSpan("observed.rh_pct", num(observed.rh_pct, "%"))}</dd>
          <dt>气压</dt><dd>${refSpan(
            "observed.pressure_msl_hpa",
            num(observed.pressure_msl_hpa, "hPa"),
          )}</dd>
          <dt>风</dt><dd>${refSpan(
            "observed.wind_speed_ms",
            `${num(observed.wind_dir_deg, "°")} ${num(observed.wind_speed_ms, "m/s")}`,
          )}</dd>
          <dt>能见度</dt><dd>${refSpan("observed.visibility_m", num(observed.visibility_m, "m"))}</dd>
          <dt>时刻</dt><dd>${esc((observed.valid_time ?? "").replace("T", " ").slice(0, 16))}（${num(
            observed.age_minutes,
            "分钟前",
            0,
          )}）</dd>
        </dl>
      </details>`
    : "";

  const observedBody = observed.available
    ? `<section class="section">
        <h3>现在实况 <span class="tag tag-observed">本地</span>
          <span class="hint-inline">和风格点实况，就在目标坐标上</span></h3>
        ${localBlock}
        ${stationDetail}
        <div class="warn ${rep && rep.level === "低" ? "degraded" : ""}">
          代表性 <strong>${esc(rep?.level ?? "未知")}</strong>：${esc(rep?.reason ?? "")}
        </div>
        <dl class="kv">
          ${
            observed.temp_adjusted
              ? `<dt>海拔订正</dt><dd>${refSpan(
                  "observed.temp_adjusted.temp_c",
                  num(observed.temp_adjusted.temp_c, "°C"),
                )} <span class="hint-inline">自算，按 ${num(
                  observed.temp_adjusted.lapse_rate_c_per_km,
                  "°C/km",
                )}</span></dd>`
              : ""
          }
          <dt>露点</dt><dd>${refSpan("observed.dewpoint_c", num(observed.dewpoint_c, "°C"))}</dd>
          <dt>湿度</dt><dd>${refSpan("observed.rh_pct", num(observed.rh_pct, "%"))}</dd>
          <dt>气压</dt><dd>${refSpan(
            "observed.pressure_msl_hpa",
            num(observed.pressure_msl_hpa, "hPa"),
          )}</dd>
          <dt>风</dt><dd>${refSpan(
            "observed.wind_speed_ms",
            `${num(observed.wind_dir_deg, "°")} ${num(observed.wind_speed_ms, "m/s")}`,
          )}</dd>
          <dt>能见度</dt><dd>${refSpan("observed.visibility_m", num(observed.visibility_m, "m"))}</dd>
          <dt>站点</dt><dd>${esc(observed.station?.id)} ${esc(observed.station?.name)}（${num(
            observed.station?.distance_km,
            "km",
          )}）</dd>
          <dt>时刻</dt><dd>${esc((observed.valid_time ?? "").replace("T", " ").slice(0, 16))}（${num(
            observed.age_minutes,
            "分钟前",
            0,
          )}）</dd>
        </dl>
      </section>`
    : `<section class="section"><h3>观测</h3>
        <div class="warn degraded">本次无可用观测：${esc(observed.error ?? "附近无 METAR 站")}</div>
      </section>`;

  // ---- 预报 ----
  const forecastRows = (forecast?.daily ?? [])
    .slice(0, 7)
    .map(
      (day, index) => `
      <tr class="${index === 0 ? "is-today" : ""}">
        <td>${esc(day.date.slice(5))}</td>
        <td>${refSpan(`forecast.daily.${index}.temp_max.mean`, stat(day.temp_max))}</td>
        <td>${refSpan(`forecast.daily.${index}.temp_min.mean`, stat(day.temp_min))}</td>
        <td>${refSpan(`forecast.daily.${index}.precip_mm.mean`, stat(day.precip_mm))}</td>
        <td>${refSpan(`forecast.daily.${index}.wind_max_ms.mean`, stat(day.wind_max_ms))}</td>
      </tr>`,
    )
    .join("");
  const agreement = Object.entries(forecast?.agreement ?? {})
    .map(([name, info]) => `${AGREEMENT_LABELS[name] ?? name} ${esc(info.level)}`)
    .join("　");

  const forecastBlock = forecastRows
    ? `<section class="section">
        <h3>预报 <span class="count">${forecast?.models.length ?? 0}</span>
          <span class="hint-inline">多模式，数字为均值±离散度</span></h3>
        <table class="forecast">
          <thead><tr><th>日期</th><th>最高 °C</th><th>最低 °C</th><th>降水 mm</th><th>风 m/s</th></tr></thead>
          <tbody>${forecastRows}</tbody>
        </table>
        <p class="hint">一致性：${agreement || "缺"}（离散度越小越一致）</p>
      </section>`
    : `<section class="section"><h3>预报</h3><p class="hint">无预报数据</p></section>`;

  // ---- 环流 ----
  const pattern = synoptic?.pattern;
  const synopticBlock = `<section class="section">
      <h3>环流 <span class="tag tag-inference">推断</span></h3>
      <div class="metrics compact">
        ${metricCard("500hPa 高度", num(synoptic?.h500_geopotential_m), "m", "观测",
          "synoptic.h500_geopotential_m", "", "tag-observed")}
        ${metricCard("850hPa 气温", num(synoptic?.t850_c), "°C", "观测",
          "synoptic.t850_c", "", "tag-observed")}
        ${metricCard("850hPa 风", num(synoptic?.wind850_speed_ms), "m/s", "观测",
          "synoptic.wind850_speed_ms", "", "tag-observed")}
      </div>
      <p class="pattern" data-ref="synoptic.pattern">${esc(pattern?.label ?? "缺")}
        <span class="hint">（规则判定，非模型生成）</span></p>
    </section>`;

  const derivedItems = pack.derived ?? {};
  const derivedCards: string[] = [];
  if (derivedItems.wind_chill_c) {
    const item = derivedItems.wind_chill_c;
    derivedCards.push(
      metricCard("体感温度", num(item.value), item.unit, "自算", "derived.wind_chill_c.value",
        item.method, "tag-derived"),
    );
  }
  if (derivedItems.thickness_850_500) {
    const item = derivedItems.thickness_850_500;
    derivedCards.push(
      metricCard("850hPa 反算高度", num(item.h850_estimated_m), "m", "自算",
        "derived.thickness_850_500.h850_estimated_m", "静力学厚度反算", "tag-derived"),
      metricCard("850–500 递减率", num(item.value), item.unit, "自算",
        "derived.thickness_850_500.value", item.stability ?? "", "tag-derived"),
    );
  }
  if (derivedItems.pressure_tendency) {
    const item = derivedItems.pressure_tendency;
    derivedCards.push(
      metricCard("3 小时变压", num(item.value), item.unit, "自算", "derived.pressure_tendency.value",
        item.label ?? "", "tag-derived"),
    );
  }
  const derivedBlock = derivedCards.length
    ? `<section class="section">
        <h3>自算 <span class="tag tag-derived">自算</span>
          <span class="hint-inline">项目按公式计算，不是观测也不是预报</span></h3>
        <div class="metrics compact">${derivedCards.join("")}</div>
        <details class="notes"><summary>公式与局限</summary>
          <ul class="caveats">
            ${Object.entries(derivedItems)
              .map(
                ([, item]) =>
                  `<li><strong>${esc(item.method)}</strong>：${esc(item.formula ?? "")}${
                    item.confidence ? `（${esc(item.confidence)}）` : ""
                  }</li>`,
              )
              .join("")}
          </ul>
        </details>
      </section>`
    : "";

  const climateBlock = `<section class="section">
      <h3>气候</h3>
      <p class="climate">
        ${esc(climate?.season ?? "缺")}　ENSO ${
          climate?.enso
            ? `${esc(climate.enso.phase)}（ONI ${num(climate.enso.oni, "", 2)}，${esc(
                climate.enso.month,
              )}）`
            : "缺"
        }
      </p>
      ${
        missing.length
          ? `<p class="hint">未覆盖：${missing.map(esc).join("；")}</p>`
          : `<p class="hint">数据链完整，无未覆盖项。</p>`
      }
    </section>`;

  container.innerHTML = `
    <div class="fact-head">
      <div class="fact-title">${esc(location.name)}<span>${esc(location.admin)}</span></div>
      <div class="fact-sub">${location.lat.toFixed(4)}, ${location.lon.toFixed(4)} ·
        海拔 ${num(location.elevation_m, "m", 0)} · ${esc(pack.generated_at.replace("T", " ").slice(0, 16))}</div>
      <div class="fact-id">${esc(pack.fact_pack_id.slice(0, 23))}…</div>
    </div>
    <div class="metrics">${metrics.join("")}</div>
    ${warningsBlock}
    ${observedBody}
    ${forecastBlock}
    ${synopticBlock}
    ${derivedBlock}
    ${climateBlock}
  `;

  // 复制预警原文（原文照搬，用户点一下即可拿到全文）
  container.querySelectorAll<HTMLButtonElement>(".copy-btn").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      const text = button.dataset.copy ?? "";
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "已复制";
      } catch {
        button.textContent = "复制失败";
      }
    });
  });
}

export function renderCharts(container: HTMLElement, charts: Chart[]): void {
  if (!charts.length) {
    container.innerHTML = `<h2>天气图</h2><p class="hint">暂无可用天气图（JMA / 中央气象台不可达）。</p>`;
    return;
  }
  const isImage = (url: string) => /\.(png|jpe?g)$/i.test(url);
  const items = charts
    .map(
      (chart) => `
      <a class="chart-card" href="${esc(chart.url)}" target="_blank" rel="noreferrer noopener">
        ${isImage(chart.url) ? `<img src="${esc(chart.url)}" alt="${esc(chart.title)}" loading="lazy" />` : ""}
        <span class="chart-title">${esc(chart.title)}</span>
        ${chart.valid_time ? `<span class="chart-time">${esc(chart.valid_time.replace("T", " ").slice(5, 16))}</span>` : ""}
      </a>`,
    )
    .join("");
  container.innerHTML = `
    <h2>天气图 <span class="count">${charts.length}</span></h2>
    <div class="charts">${items}</div>
    <p class="hint">须署名：JMA / 中央气象台。点击外链查看原图。</p>
  `;
}

export function answerBubble(answer: Answer): HTMLElement {
  const bubble = document.createElement("div");
  bubble.className = "bubble answer";

  const facts = (answer.facts ?? [])
    .map(
      (fact) =>
        `<div class="fact clickable" data-ref="${esc(fact.ref)}" title="点击定位到事实包">` +
        `<span class="fact-label">${esc(fact.label)}</span>` +
        `<span class="fact-value">${esc(fact.value)}</span>` +
        `<code>${esc(fact.ref)}</code></div>`,
    )
    .join("");
  const degraded = answer.degraded
    ? `<div class="warn degraded">本次未生成解释（降级为事实罗列）：${esc(
        answer.fallback_reason ?? "",
      )}</div>`
    : "";
  const citations = (answer.citations ?? [])
    .slice(0, 6)
    .map((url) => {
      let host = url;
      try {
        host = new URL(url).hostname.replace(/^www\./, "");
      } catch {
        /* 非 URL 就原样显示 */
      }
      return `<a href="${esc(url)}" target="_blank" rel="noreferrer noopener">${esc(host)}</a>`;
    })
    .join("");

  bubble.innerHTML = `
    <h3>${esc(answer.headline)}</h3>
    ${degraded}
    <div class="facts">${facts}</div>
    <p class="answer-section"><span class="tag tag-observed">观测</span>${esc(answer.observed)}</p>
    <p class="answer-section"><span class="tag tag-forecast">预报</span>${esc(answer.forecast)}</p>
    <p class="answer-section"><span class="tag tag-inference">推断</span>${esc(
      answer.inference?.text,
    )}<br />
      <span class="hint">置信度 ${esc(answer.inference?.confidence)}｜依据 ${esc(
        (answer.inference?.basis ?? []).join("、") || "无",
      )}</span></p>
    <p class="hint">不确定性：${esc(answer.uncertainty)}</p>
    <p class="hint">建议：${esc(answer.advice)}</p>
    ${
      answer.not_covered?.length
        ? `<p class="hint">未覆盖：${esc(answer.not_covered.join("；"))}</p>`
        : ""
    }
    <p class="citations">${citations}</p>
    <p class="ref-hint"></p>
  `;

  const hint = bubble.querySelector<HTMLElement>(".ref-hint");
  bubble.querySelectorAll<HTMLElement>(".fact[data-ref]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const ref = chip.dataset.ref ?? "";
      const result = focusRef(ref);
      if (hint) {
        hint.textContent =
          result === "dom"
            ? `已在事实包中定位：${ref}`
            : result === "pack"
              ? `该数值在事实包中存在，但面板未展示：${ref}`
              : `事实包里没有这个路径：${ref}（模型可能编造了引用）`;
        hint.style.color = result === "missing" ? "var(--danger)" : "";
      }
    });
  });
  return bubble;
}
