// 与后端的数据契约（只声明前端用得到的部分，其余原样透传）

export interface Stat {
  mean: number | null;
  p10: number | null;
  p90: number | null;
  spread: number | null;
}

export interface DailyForecast {
  date: string;
  temp_max: Stat;
  temp_min: Stat;
  precip_mm: Stat;
  wind_max_ms: Stat;
}

export interface Chart {
  title: string;
  url: string;
  valid_time: string | null;
  license: string;
  kind: string;
}

export interface FactPack {
  schema_version: string;
  fact_pack_id: string;
  generated_at: string;
  location: {
    name: string;
    admin: string;
    lat: number;
    lon: number;
    elevation_m: number | null;
    geocode_source: string;
    geocode_confidence: number;
  };
  observed: {
    available: boolean;
    error?: string;
    station?: { id: string; name: string; distance_km: number; elevation_m: number | null };
    valid_time?: string;
    age_minutes?: number;
    temp_c?: number | null;
    dewpoint_c?: number | null;
    rh_pct?: number | null;
    pressure_msl_hpa?: number | null;
    pressure_trend_3h_hpa?: number | null;
    wind_dir_deg?: number | null;
    wind_speed_ms?: number | null;
    wind_gust_ms?: number | null;
    visibility_m?: number | null;
    weather_code?: string | null;
    source?: string;
    source_url?: string;
    representativeness?: { level: string; reason: string };
  };
  trend_24h: Record<string, number | string> | null;
  forecast: {
    models: string[];
    daily: DailyForecast[];
    agreement: Record<string, { level: string; spread: number; basis?: string }>;
  } | null;
  synoptic: {
    h500_geopotential_m: number | null;
    t500_c: number | null;
    t850_c: number | null;
    wind850_dir_deg: number | null;
    wind850_speed_ms: number | null;
    valid_time: string | null;
    source_url: string | null;
    charts: Chart[];
    pattern: { label: string; confidence: string; basis: string[] };
  } | null;
  climate: {
    season: string;
    enso: { phase: string; oni: number | null; month: string; source: string } | null;
  } | null;
  warnings: Array<{ title: string; text: string }>;
  provenance: {
    providers: Array<{ name: string; ok: boolean; latency_ms: number; error?: string }>;
    missing: string[];
    notes: string[];
  };
}

export interface Answer {
  headline: string;
  facts: Array<{ label: string; value: string; ref: string }>;
  observed: string;
  forecast: string;
  inference: { text: string; confidence: string; basis: string[] };
  uncertainty: string;
  advice: string;
  not_covered: string[];
  citations: string[];
  degraded: boolean;
  fallback_reason?: string;
}

export interface SiteConfig {
  tianditu_key: string | null;
  map_approval_no: string | null;
  attribution: { basemap: string; clouds: string };
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body?.detail?.error ?? body?.detail ?? detail;
    } catch {
      /* 保留状态码信息 */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function fetchFactPack(place: string, days = 7): Promise<FactPack> {
  return getJson<FactPack>(`/api/fact_pack?place=${encodeURIComponent(place)}&days=${days}`);
}

/** 前端需要的公开配置：天地图 key（浏览器端 key，服务端请求会被拒）。 */
export function fetchSiteConfig(): Promise<SiteConfig> {
  return getJson<SiteConfig>("/api/config");
}

export async function fetchCharts(): Promise<Chart[]> {
  const body = await getJson<{ charts: Chart[]; error?: string }>("/api/charts");
  return body.charts ?? [];
}

export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

/** 读 SSE：按空行切事件，event/data 两行一组。 */
export async function streamExplain(
  place: string,
  days: number,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/api/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ place, days }),
    signal,
  });
  if (!response.ok || response.body === null) {
    throw new Error(`解释接口失败：HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          const payload = JSON.parse(line.slice(5).trim()) as Record<string, unknown>;
          onEvent({ event: eventName, data: payload });
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}
