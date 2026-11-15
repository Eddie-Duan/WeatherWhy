// 渲染：事实包、天气图、解释回答。三层信息用不同标记与配色（观测/预报/推断）。

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

const AGREEMENT_LABELS: Record<string, string> = {
  temperature_max: "最高气温",
  temperature_min: "最低气温",
  precipitation: "降水",
  wind: "风",
};

const windText = (dir?: number | null, speed?: number | null): string => {
  const direction = dir === null || dir === undefined ? "" : `${num(dir, "°")} `;
  return `${direction}${num(speed, "m/s")}`.trim();
};

export function renderFact(container: HTMLElement, pack: FactPack): void {
  const location = pack.location;
  const observed = pack.observed;
  const forecast = pack.forecast;
  const synoptic = pack.synoptic;
  const climate = pack.climate;
  const rep = observed.representativeness;

  const observedBody = observed.available
    ? `
      <div class="warn ${rep && rep.level === "低" ? "degraded" : ""}">
        <span class="tag observed">观测</span>
        ${esc(rep?.reason ?? "代表性未知")}
      </div>
      <dl class="kv">
        <dt>气温</dt><dd>${num(observed.temp_c, "°C")}（露点 ${num(observed.dewpoint_c, "°C")}）</dd>
        <dt>湿度 / 气压</dt><dd>${num(observed.rh_pct, "%")} / ${num(observed.pressure_msl_hpa, "hPa")}</dd>
        <dt>风</dt><dd>${windText(observed.wind_dir_deg, observed.wind_speed_ms)}</dd>
        <dt>能见度</dt><dd>${num(observed.visibility_m, "m")}</dd>
        <dt>站点</dt><dd>${esc(observed.station?.id)} ${esc(observed.station?.name)}（${num(
          observed.station?.distance_km,
          "km",
        )}）</dd>
        <dt>时刻</dt><dd>${esc(observed.valid_time)}（${num(observed.age_minutes, "分钟前", 0)}）</dd>
      </dl>`
    : `<div class="warn degraded">本次无可用观测：${esc(observed.error ?? "附近无 METAR 站")}</div>`;

  const forecastRows = (forecast?.daily ?? [])
    .slice(0, 7)
    .map(
      (day) => `
      <tr>
        <td>${esc(day.date)}</td>
        <td>${stat(day.temp_max)}</td>
        <td>${stat(day.temp_min)}</td>
        <td>${stat(day.precip_mm)}</td>
        <td>${stat(day.wind_max_ms)}</td>
      </tr>`,
    )
    .join("");

  const agreement = Object.entries(forecast?.agreement ?? {})
    .map(([name, info]) => `${AGREEMENT_LABELS[name] ?? name} ${esc(info.level)}`)
    .join("　");

  const pattern = synoptic?.pattern;
  const missing = pack.provenance.missing ?? [];

  container.innerHTML = `
    <h2>事实包</h2>
    <div class="kv">
      <dt>地点</dt><dd>${esc(location.name)} · ${esc(location.admin)}</dd>
      <dt>坐标</dt><dd>${location.lat.toFixed(4)}, ${location.lon.toFixed(4)}</dd>
      <dt>海拔</dt><dd>${num(location.elevation_m, "m", 0)}</dd>
    </div>
    <p class="muted small">fact_pack_id ${esc(pack.fact_pack_id)}<br />生成于 ${esc(pack.generated_at)}</p>
    ${observedBody}
    <div class="section-title"><span class="tag forecast">预报</span>多模式 ${
      forecast?.models.length ?? 0
    } 个（离散度越小越一致）</div>
    ${
      forecastRows
        ? `<table class="forecast">
            <thead><tr><th>日期</th><th>最高 °C</th><th>最低 °C</th><th>降水 mm</th><th>风 m/s</th></tr></thead>
            <tbody>${forecastRows}</tbody>
          </table>
          <p class="muted small">一致性：${agreement || "缺"}</p>`
        : `<p class="muted">无预报数据</p>`
    }
    <div class="section-title"><span class="tag inference">推断</span>环流背景</div>
    <dl class="kv">
      <dt>500hPa</dt><dd>${num(synoptic?.h500_geopotential_m, "m", 0)}</dd>
      <dt>850hPa</dt><dd>${num(synoptic?.t850_c, "°C")} / ${num(synoptic?.wind850_speed_ms, "m/s")}</dd>
      <dt>环流型</dt><dd>${esc(pattern?.label ?? "缺")}</dd>
    </dl>
    <p class="muted small">气候：${esc(climate?.season ?? "缺")}｜ENSO ${
      climate?.enso ? `${esc(climate.enso.phase)}（ONI ${num(climate.enso.oni, "", 2)}）` : "缺"
    }</p>
    ${missing.length ? `<p class="muted small">未覆盖：${missing.map(esc).join("；")}</p>` : ""}
  `;
}

export function renderCharts(container: HTMLElement, charts: Chart[]): void {
  if (!charts.length) {
    container.innerHTML = `<h2>天气图</h2><p class="muted">暂无可用天气图（JMA / 中央气象台不可达）。</p>`;
    return;
  }
  const isImage = (url: string) => /\.(png|jpe?g)$/i.test(url);
  const items = charts
    .map(
      (chart) => `
      <a href="${esc(chart.url)}" target="_blank" rel="noreferrer noopener">
        ${isImage(chart.url) ? `<img src="${esc(chart.url)}" alt="${esc(chart.title)}" loading="lazy" />` : ""}
        ${esc(chart.title)}
      </a>`,
    )
    .join("");
  container.innerHTML = `
    <h2>天气图</h2>
    <div class="charts">${items}</div>
    <p class="muted small">须署名：JMA / 中央气象台。点击外链查看原图。</p>
  `;
}

export function answerBubble(answer: Answer): HTMLElement {
  const bubble = document.createElement("div");
  bubble.className = "bubble answer";

  const facts = (answer.facts ?? [])
    .map(
      (fact) =>
        `<div class="fact">${esc(fact.label)} ${esc(fact.value)}<code>${esc(fact.ref)}</code></div>`,
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
      return `<a href="${esc(url)}" target="_blank" rel="noreferrer noopener" class="muted small">${esc(host)}</a>`;
    })
    .join(" ");

  bubble.innerHTML = `
    <h3>${esc(answer.headline)}</h3>
    ${degraded}
    <div class="facts">${facts}</div>
    <p><span class="tag observed">观测</span>${esc(answer.observed)}</p>
    <p><span class="tag forecast">预报</span>${esc(answer.forecast)}</p>
    <p><span class="tag inference">推断</span>${esc(answer.inference?.text)}<br />
      <span class="muted small">置信度 ${esc(answer.inference?.confidence)}｜依据 ${esc(
        (answer.inference?.basis ?? []).join("、") || "无",
      )}</span></p>
    <p class="muted small">不确定性：${esc(answer.uncertainty)}</p>
    <p class="muted small">建议：${esc(answer.advice)}</p>
    ${
      answer.not_covered?.length
        ? `<p class="muted small">未覆盖：${esc(answer.not_covered.join("；"))}</p>`
        : ""
    }
    <p class="muted small">${citations}</p>
  `;
  return bubble;
}
