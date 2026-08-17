import re

with open('app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add currentGeeOverlay variable
content = content.replace("let plotBaseLayers = {};", "let plotBaseLayers = {};\nlet currentGeeOverlay = null;")

# 2. Modify initPlotSatelliteMap
init_map_old = """  plotBaseLayers['s2'] = L.tileLayer.wms('https://tiles.maps.eox.at/wms', {
    layers: 's2cloudless-2023',
    format: 'image/jpeg',
    transparent: false,
    maxZoom: 18
  });

  // Color Infrared vegetation filter simulation tile
  plotBaseLayers['cir'] = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    className: 'leaflet-tile-cir'
  });

  // NDVI False color filter simulation tile
  plotBaseLayers['ndvi'] = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    className: 'leaflet-tile-ndvi'
  });"""

content = content.replace(init_map_old, "")

# 3. Modify setPlotMapLayer
set_layer_old = """function setPlotMapLayer(layerKey) {
  currentPlotLayerKey = layerKey;
  
  document.querySelectorAll('.band-btn-group .band-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.layer === layerKey);
  });

  // Switch base layer
  Object.values(plotBaseLayers).forEach(layer => {
    if (plotSatelliteMap.hasLayer(layer)) {
      plotSatelliteMap.removeLayer(layer);
    }
  });

  if (plotBaseLayers[layerKey]) {
    plotBaseLayers[layerKey].addTo(plotSatelliteMap);
  }

  // Ensure boundary layer stays on top
  if (plotBoundaryLayer && plotSatelliteMap.hasLayer(plotBoundaryLayer)) {
    plotBoundaryLayer.bringToFront();
  }
}"""

set_layer_new = """function setPlotMapLayer(layerKey) {
  currentPlotLayerKey = layerKey;
  
  document.querySelectorAll('.band-btn-group .band-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.layer === layerKey);
  });

  if (currentGeeOverlay && plotSatelliteMap.hasLayer(currentGeeOverlay)) {
    plotSatelliteMap.removeLayer(currentGeeOverlay);
  }

  if (!plotSatelliteMap.hasLayer(plotBaseLayers['esri'])) {
    plotBaseLayers['esri'].addTo(plotSatelliteMap);
  }

  if (layerKey !== 'esri') {
    updateGeeOverlay();
  }

  if (plotBoundaryLayer && plotSatelliteMap.hasLayer(plotBoundaryLayer)) {
    plotBoundaryLayer.bringToFront();
  }
}

const MILESTONE_MONTHS = [
  '2023-09', '2023-12', '2024-03', '2024-06',
  '2024-09', '2024-12', '2025-03', '2025-06',
  '2025-09', '2025-12', '2026-03', '2026-08'
];

function updateGeeOverlay() {
  if (!activePlot || !plotSatelliteMap) return;
  if (currentPlotLayerKey !== 'gee_rgb' && currentPlotLayerKey !== 'gee_ndvi') return;

  const item = activePlot.timeseries[currentMonthIndex];
  if (!item) return;

  const targetVal = item.year * 12 + item.month_num;
  let closestMilestone = MILESTONE_MONTHS[0];
  let minDiff = 999;
  
  MILESTONE_MONTHS.forEach(m => {
    const [y, mm] = m.split('-').map(Number);
    const val = y * 12 + mm;
    if (Math.abs(val - targetVal) < minDiff) {
      minDiff = Math.abs(val - targetVal);
      closestMilestone = m;
    }
  });

  const prefix = currentPlotLayerKey === 'gee_rgb' ? 'rgb' : 'ndvi';
  // Use timestamp to prevent caching issues if images are updated
  const imageUrl = `data/plots/${activePlot.id}/${prefix}_${closestMilestone}.png`;
  
  const buf = 0.003;
  const b = activePlot.bounds;
  const imageBounds = [
    [b[1] - buf, b[0] - buf],
    [b[3] + buf, b[2] + buf]
  ];

  if (currentGeeOverlay && plotSatelliteMap.hasLayer(currentGeeOverlay)) {
    plotSatelliteMap.removeLayer(currentGeeOverlay);
  }

  currentGeeOverlay = L.imageOverlay(imageUrl, imageBounds, {opacity: 1.0});
  currentGeeOverlay.addTo(plotSatelliteMap);
  
  if (plotBoundaryLayer && plotSatelliteMap.hasLayer(plotBoundaryLayer)) {
    plotBoundaryLayer.bringToFront();
  }
}"""

content = content.replace(set_layer_old, set_layer_new)

# 4. Inject updateGeeOverlay into setMonthIndex
if "updateGeeOverlay();" not in content:
    content = content.replace(
        "document.getElementById('hud-in-cover').textContent = `${item.canopy_coverage_pct.toFixed(1)}%`;",
        "document.getElementById('hud-in-cover').textContent = `${item.canopy_coverage_pct.toFixed(1)}%`;\n\n  // Update GEE Overlay for current month\n  updateGeeOverlay();"
    )

# 5. Inject updateGeeOverlay into selectPlot
if "updateGeeOverlay();" not in content.split("function selectPlot")[1].split("}")[0]:
     content = content.replace(
        "updatePlotSatelliteViewer(plot);",
        "updatePlotSatelliteViewer(plot);\n\n  // Load GEE image if active\n  updateGeeOverlay();"
    )

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patched app.js successfully!")
