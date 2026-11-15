// 地图：天地图底图（有 key 时）+ NASA GIBS 云图叠加 + 位置标记。
// 天地图 key 由后端 /api/config 下发（浏览器端 key，服务端请求会被拒），
// 没有 key 时降级为纯色底图 + 云图（设计文档 §7），不会白屏。

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

function isoDay(offsetDays: number): string {
  const date = new Date(Date.now() + offsetDays * 86_400_000);
  return date.toISOString().slice(0, 10);
}

const GIBS_TILES =
  "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/" +
  `${isoDay(-1)}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`;

export interface SkyMap {
  map: maplibregl.Map;
  hasBasemap: boolean;
  setCloudVisible(visible: boolean): void;
  goTo(lat: number, lon: number, label: string): void;
}

const TILE_TEMPLATE = (key: string, matrix: string) =>
  `https://t0.tianditu.gov.cn/${matrix}_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0` +
  `&LAYER=${matrix}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles` +
  `&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${key}`;

export function createMap(container: string, basemapKey = ""): SkyMap {
  const sources: Record<string, unknown> = {};
  const layers: unknown[] = [
    { id: "bg", type: "background", paint: { "background-color": "#0d141d" } },
  ];

  if (basemapKey) {
    // 矢量底图与注记层必须分成两个 source（同一个 source 的 tiles 数组表示同一层的多个地址）
    sources["tianditu-vec"] = {
      type: "raster",
      tiles: [TILE_TEMPLATE(basemapKey, "vec")],
      tileSize: 256,
      attribution: "天地图",
    };
    sources["tianditu-cva"] = {
      type: "raster",
      tiles: [TILE_TEMPLATE(basemapKey, "cva")],
      tileSize: 256,
      attribution: "天地图",
    };
    layers.push(
      { id: "tianditu-vec", type: "raster", source: "tianditu-vec" },
      { id: "tianditu-cva", type: "raster", source: "tianditu-cva" },
    );
  }

  const map = new maplibregl.Map({
    container,
    style: { version: 8, sources, layers } as unknown as maplibregl.StyleSpecification,
    center: [115, 42.3],
    zoom: 3.4,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  const markerEl = document.createElement("div");
  markerEl.className = "marker";
  markerEl.title = "当前位置";
  const marker = new maplibregl.Marker({ element: markerEl }).setLngLat([115, 42.3]);

  map.on("load", () => {
    map.addSource("gibs", {
      type: "raster",
      tiles: [GIBS_TILES],
      tileSize: 256,
      attribution: "NASA GIBS",
    });
    // 云图压在底图之上、注记之下：地名/道路保持清晰可读
    const beforeId = map.getLayer("tianditu-cva") ? "tianditu-cva" : undefined;
    map.addLayer(
      { id: "gibs", type: "raster", source: "gibs", paint: { "raster-opacity": 0.6 } },
      beforeId,
    );
    marker.addTo(map);
  });

  return {
    map,
    hasBasemap: Boolean(basemapKey),
    setCloudVisible(visible: boolean) {
      if (map.getLayer("gibs")) {
        map.setLayoutProperty("gibs", "visibility", visible ? "visible" : "none");
      }
    },
    goTo(lat: number, lon: number, name: string) {
      marker.setLngLat([lon, lat]);
      markerEl.title = name;
      map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 5.5), duration: 900 });
    },
  };
}
