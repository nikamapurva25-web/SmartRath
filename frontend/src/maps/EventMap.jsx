import { useEffect, useRef, useState } from "react";
import { Map as MapLibreMap, NavigationControl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const featureCollection = (features) => ({
  type: "FeatureCollection",
  features,
});

function EventMap({ events = [], buses = [], trails = {}, activeLayer = "infrastructure" }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const readyRef = useRef(false);
  const [mapReady, setMapReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return undefined;
    const map = new MapLibreMap({
      container: containerRef.current,
      style: "https://demotiles.maplibre.org/style.json",
      center: [73.8567, 18.5204],
      zoom: 12,
    });
    mapRef.current = map;
    map.addControl(new NavigationControl(), "top-left");

    map.on("load", () => {
      map.addSource("infrastructure-events", { type: "geojson", data: featureCollection([]) });
      map.addSource("traffic-events", { type: "geojson", data: featureCollection([]) });
      map.addSource("safety-events", { type: "geojson", data: featureCollection([]) });

      map.addLayer({
        id: "infrastructure-heat",
        type: "heatmap",
        source: "infrastructure-events",
        filter: ["==", ["get", "event_type"], "infrastructure"],
        paint: {
          "heatmap-weight": ["interpolate", ["linear"], ["get", "members"], 1, 0.4, 10, 1],
          "heatmap-intensity": 0.8,
          "heatmap-radius": 28,
          "heatmap-opacity": 0.75,
          "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"], 0, "rgba(34,197,94,0)", 0.35, "#facc15", 0.7, "#f97316", 1, "#ef4444"],
        },
      });
      map.addLayer({
        id: "infrastructure-clusters",
        type: "circle",
        source: "infrastructure-events",
        filter: ["==", ["get", "event_type"], "infrastructure"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "members"], 1, 6, 10, 13],
          "circle-color": "#f97316",
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "traffic-buses",
        type: "circle",
        source: "traffic-events",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": 8,
          "circle-color": ["case", ["get", "bottleneck"], "#ef4444", "#22c55e"],
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "traffic-trails",
        type: "line",
        source: "traffic-events",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: {
          "line-color": ["case", ["get", "bottleneck"], "#ef4444", "#22c55e"],
          "line-width": 3,
          "line-opacity": 0.8,
        },
      });
      map.addLayer({
        id: "traffic-count-labels",
        type: "symbol",
        source: "traffic-events",
        filter: ["==", ["geometry-type"], "Point"],
        layout: {
          "text-field": ["concat", ["get", "bus_id"], " · ", ["to-string", ["get", "vehicle_count"]], " veh"],
          "text-offset": [0, 1.5],
          "text-size": 11,
        },
        paint: { "text-color": "#fff", "text-halo-color": "#0f172a", "text-halo-width": 1.5 },
      });
      map.addLayer({
        id: "safety-alerts",
        type: "circle",
        source: "safety-events",
        paint: {
          "circle-radius": 12,
          "circle-color": "#ef4444",
          "circle-opacity": 0.9,
          "circle-stroke-color": "#fecaca",
          "circle-stroke-width": 3,
        },
      });
      readyRef.current = true;
      setMapReady(true);
    });

    let pulse = 0;
    const pulseTimer = window.setInterval(() => {
      if (!readyRef.current || !map.getLayer("safety-alerts")) return;
      pulse += 1;
      map.setPaintProperty("safety-alerts", "circle-radius", 10 + (pulse % 2) * 5);
      map.setPaintProperty("safety-alerts", "circle-opacity", pulse % 2 ? 1 : 0.55);
    }, 550);

    return () => {
      window.clearInterval(pulseTimer);
      readyRef.current = false;
      setMapReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const pointFeatures = (values) => values
      .filter((event) => Number.isFinite(Number(event.lat)) && Number.isFinite(Number(event.lng)))
      .map((event) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [Number(event.lng), Number(event.lat)] },
        properties: { ...event },
      }));

    const infrastructure = events.filter((event) => event.event_type === "infrastructure");
    const trafficEvents = events.filter((event) => event.event_type === "congestion_bottleneck");
    const safety = events.filter((event) => event.event_type === "anpr_alert" || event.event_type === "safety_risk");
    const infrastructureSource = map.getSource("infrastructure-events");
    const trafficSource = map.getSource("traffic-events");
    const safetySource = map.getSource("safety-events");
    if (infrastructureSource) infrastructureSource.setData(featureCollection(pointFeatures(infrastructure)));
    if (safetySource) safetySource.setData(featureCollection(pointFeatures(safety)));

    const busFeatures = buses.map((bus) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [Number(bus.lng), Number(bus.lat)] },
      properties: {
        bus_id: bus.bus_id,
        vehicle_count: bus.vehicle_count || 0,
        bottleneck: bus.speed_kmh != null && bus.baseline_speed_kmh != null
          && bus.speed_kmh < bus.baseline_speed_kmh * 0.6,
      },
    }));
    const trailFeatures = Object.entries(trails)
      .filter(([, points]) => points.length > 1)
      .map(([busId, points]) => ({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: points.map((point) => [Number(point.lng), Number(point.lat)]),
        },
        properties: {
          bus_id: busId,
          bottleneck: points.at(-1).speed_kmh != null
            && points.at(-1).baseline_speed_kmh != null
            && points.at(-1).speed_kmh < points.at(-1).baseline_speed_kmh * 0.6,
        },
      }));
    if (trafficSource) trafficSource.setData(featureCollection([...busFeatures, ...trailFeatures, ...pointFeatures(trafficEvents)]));
  }, [events, buses, trails, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const layerGroups = {
      infrastructure: ["infrastructure-heat", "infrastructure-clusters"],
      traffic: ["traffic-buses", "traffic-trails", "traffic-count-labels"],
      safety: ["safety-alerts"],
    };
    for (const [group, layerIds] of Object.entries(layerGroups)) {
      for (const layerId of layerIds) {
        if (map.getLayer(layerId)) {
          map.setLayoutProperty(layerId, "visibility", group === activeLayer ? "visible" : "none");
        }
      }
    }
  }, [activeLayer, mapReady]);

  return <div ref={containerRef} className="event-map" />;
}

export default EventMap;
