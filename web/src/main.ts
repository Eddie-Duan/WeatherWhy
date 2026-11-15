// 入口：加载天气图 → 查询地点 → 渲染事实包/地图 → 接线对话。

import "./theme.css";
import { fetchCharts, fetchFactPack, type FactPack } from "./api";
import { createChat } from "./chat";
import { createMap, hasBasemap } from "./map";
import { renderCharts, renderFact } from "./panels";

const $ = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!element) throw new Error(`缺少元素 #${id}`);
  return element as T;
};

const placeInput = $<HTMLInputElement>("place");
const placeForm = $<HTMLFormElement>("place-form");
const status = $<HTMLElement>("status");
const factPanel = $<HTMLElement>("fact-panel");
const chartsPanel = $<HTMLElement>("charts-panel");
const messages = $<HTMLElement>("messages");
const askForm = $<HTMLFormElement>("ask-form");
const question = $<HTMLInputElement>("question");
const chatNote = $<HTMLElement>("chat-note");
const cloudToggle = $<HTMLInputElement>("cloud-toggle");
const basemapNote = $<HTMLElement>("basemap-note");
const locationBadge = $<HTMLElement>("location-badge");

const skyMap = createMap("map");
basemapNote.textContent = hasBasemap()
  ? "底图：天地图（已审图）"
  : "未配置 VITE_TIANDITU_KEY：纯色底图 + 云图";

let current: FactPack | null = null;

const setStatus = (text: string): void => {
  status.textContent = text;
};

const setBusy = (busy: boolean): void => {
  for (const button of Array.from(document.querySelectorAll("button"))) {
    button.disabled = busy;
  }
};

async function loadPlace(place: string): Promise<void> {
  setBusy(true);
  setStatus(`正在组装 ${place} 的事实包（确定性取数，不走 LLM）…`);
  try {
    const pack = await fetchFactPack(place);
    current = pack;
    renderFact(factPanel, pack);
    skyMap.goTo(pack.location.lat, pack.location.lon, pack.location.name);
    locationBadge.hidden = false;
    locationBadge.textContent = `${pack.location.name}（${pack.location.admin}）· ${
      pack.observed.available ? `观测 ${pack.observed.station?.id ?? ""}` : "无可用观测"
    }`;
    const slow = pack.provenance.providers
      .filter((provider) => !provider.ok)
      .map((provider) => provider.name);
    setStatus(
      `${pack.location.name} 已加载｜fact_pack_id ${pack.fact_pack_id.slice(0, 16)}…` +
        (slow.length ? `｜降级：${slow.join(", ")}` : ""),
    );
  } catch (error) {
    setStatus(`加载失败：${error instanceof Error ? error.message : String(error)}`);
  } finally {
    setBusy(false);
  }
}

placeForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const place = placeInput.value.trim();
  if (place) void loadPlace(place);
});

cloudToggle.addEventListener("change", () => {
  skyMap.setCloudVisible(cloudToggle.checked);
});

createChat({
  messages,
  form: askForm,
  input: question,
  note: chatNote,
  place: () => current?.location.name ?? placeInput.value.trim(),
  days: () => 7,
  onBusy: setBusy,
});

void (async () => {
  try {
    renderCharts(chartsPanel, await fetchCharts());
  } catch (error) {
    chartsPanel.innerHTML = `<h2>天气图</h2><p class="muted">天气图加载失败：${
      error instanceof Error ? error.message : "未知错误"
    }</p>`;
  }
  await loadPlace(placeInput.value.trim() || "明安图镇");
})();
