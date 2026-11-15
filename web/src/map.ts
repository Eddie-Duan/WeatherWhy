// 地图：天地图底图（有 key 时）+ NASA GIBS 云图叠加 + 位置标记。
// 没有天地图 key 时降级为纯色底图 + 云图（设计文档 §7 的降级路径），不会白屏。

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const TIANDITU_KEY = (import.meta.env.VITE_TIANDITU_KEY as string | undefined) ?? "";

function isoDay(offsetDays: number): string {
  const date = new Date(Date.now() + offsetDays * 86_400_000);
  return date.toISOString().slice(0, 10);
}

const GIBS_TILES =
  "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/" +
  `${isoDay(-1)}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`;

export interface SkyMap {
  map: maplibregl.Map;
  setCloudVisible(visible: boolean): void;
  goTo(lat: number, lon: number, label: string): void;
}

export function createMap(container: string): SkyMap {
  const sources: Record<string, unknown> = {};
  const layers: unknown[] = [
    { id: "bg", type: "background", paint: { "background-color": "#0d141d" } },
  ];

  if (TIANDITU_KEY) {
    sources.tianditu = {
      type: "raster",
      tiles: [
        `https://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${TIANDITU_KEY}`,
      ],
      tileSize: 256,
      attribution: "天地图（已审图）",
    };
    layers.push({ id: "tianditu", type: "raster", source: "tianditu" });
  }

  const map = new maplibregl.Map({
    container,
    style: { version: 8, sources, layers } as unknown as maplibregl.StyleSpecification,
    center: [115, 42.3],
    zoom: 3.4,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  const label = document.createElement("div");
  label.className = "marker";
  label.title = "当前位置";
  const marker = new maplibregl.Marker({ element: label }).setLngLat([115, 42.3]);

  map.on("load", () => {
    map.addSource("gibs", {
      type: "raster",
      tiles: [GIBS_TILES],
      tileSize: 256,
      attribution: "NASA GIBS",
    });
    map.addLayer({ id: "gibs", type: "raster", source: "gibs", paint: { "raster-opacity": 0.72 } });
    marker.addTo(map);
    map.setLayoutProperty("gibs", "visibility", "visible");
  });

  return {
    map,
    setCloudVisible(visible: boolean) {
      if (map.getLayer("gibs")) {
        map.setLayoutProperty("gibs", "visibility", visible ? "visible" : "none");
      }
    },
    goTo(lat: number, lon: number, name: string) {
      marker.setLngLat([lon, lat]);
      label.title = name;
      map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 5.5), duration: 900 });
    },
  } satisfies SkyMap;
}

export function hasBasemap(): boolean {
  return Boolean(TIANDITU_KEY);
}
