// Prasae visual hotfix — 2026-08-17 22:55 ICT
// Enforces 12 real observation dates, permanent Esri compare basemap,
// and race-safe Sentinel frame swaps with no Esri flash between frames.

const HOTFIX_BUILD = '20260817-2255';
const HOTFIX_DATES = [
  '2023-09', '2023-12', '2024-03', '2024-06',
  '2024-09', '2024-12', '2025-03', '2025-06',
  '2025-09', '2025-12', '2026-03', '2026-08'
];

let hotfixPendingSentinelOverlay = null;
let hotfixSentinelSwapToken = 0;
let hotfixCompareEsriBaseLayer = null;

function hotfixParseMonthKey(monthKey) {
  const [year, month] = monthKey.split('-').map(Number);
  return { month: monthKey, year, month_num: month };
}

function hotfixFindItem(index) {
  const key = HOTFIX_DATES[Math.max(0, Math.min(HOTFIX_DATES.length - 1, Number(index) || 0))];
  const found = activePlot?.timeseries?.find(item => item.month === key);
  return found || { ...hotfixParseMonthKey(key), mean_ndvi_inside: null, vegetation_coverage_proxy_pct: null };
}

function hotfixPreloadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(url);
    image.onerror = reject;
    image.src = `${url}?v=${HOTFIX_BUILD}`;
  });
}

function hotfixForce12DateUi() {
  const slider = document.getElementById('month-slider');
  if (slider) {
    slider.min = '0';
    slider.max = String(HOTFIX_DATES.length - 1);
    slider.step = '1';
    if (Number(slider.value) > HOTFIX_DATES.length - 1) slider.value = '0';
  }

  const ticks = document.querySelector('.slider-ticks');
  if (ticks) {
    ticks.innerHTML = '<span>ก.ย. 2023</span><span>ก.ย. 2024</span><span>ก.ย. 2025</span><span>ส.ค. 2026</span>';
  }

  const datePill = document.querySelector('.date-range-pill');
  if (datePill) datePill.textContent = '12 ช่วงเวลาภาพดาวเทียม';

  const detailTab = document.getElementById('wtab-detail');
  if (detailTab) {
    const textNodes = [...detailTab.childNodes].filter(node => node.nodeType === Node.TEXT_NODE);
    const lastText = textNodes[textNodes.length - 1];
    if (lastText) lastText.textContent = ' วิเคราะห์ 12 ช่วงเวลา (Observed / Composite)';
  }

  const hud = document.querySelector('.stage-hud.top-right');
  if (hud) hud.innerHTML = '<div class="hud-tag">Cloud-masked composite</div><div class="hud-sub">12 observed/composite dates • no interpolation</div>';

  const build = document.getElementById('hotfix-build-badge');
  if (!build) {
    const badge = document.createElement('div');
    badge.id = 'hotfix-build-badge';
    badge.textContent = `build ${HOTFIX_BUILD}`;
    badge.style.cssText = 'position:fixed;right:8px;bottom:8px;z-index:99999;font:10px/1.2 monospace;color:#94a3b8;background:rgba(15,23,42,.78);padding:4px 6px;border-radius:5px;pointer-events:none';
    document.body.appendChild(badge);
  }
}

setMonthIndex = function(index) {
  if (!activePlot) return;

  const idx = Math.max(0, Math.min(HOTFIX_DATES.length - 1, Number(index) || 0));
  currentMonthIndex = idx;
  const item = hotfixFindItem(idx);

  const slider = document.getElementById('month-slider');
  if (slider) {
    slider.max = String(HOTFIX_DATES.length - 1);
    slider.value = String(idx);
  }

  const playbackDate = document.getElementById('playback-date-display');
  if (playbackDate) playbackDate.textContent = `${thaiMonths[item.month_num]} ${item.year}`;

  const monthLabel = document.getElementById('hud-month-label');
  if (monthLabel) monthLabel.textContent = `${fullThaiMonths[item.month_num]} ${item.year}`;

  const plotLabel = document.getElementById('hud-plot-label');
  if (plotLabel) plotLabel.textContent = `${activePlot.name} (${activePlot.province})`;

  const coords = document.getElementById('hud-coords-label');
  if (coords) coords.textContent = `${activePlot.centroid[0].toFixed(4)}°N, ${activePlot.centroid[1].toFixed(4)}°E • ${Number(activePlot.area_rai).toFixed(1)} ไร่`;

  const ndvi = document.getElementById('hud-in-ndvi');
  if (ndvi) ndvi.textContent = isFiniteNumber(item.mean_ndvi_inside) ? item.mean_ndvi_inside.toFixed(3) : '—';

  const proxy = document.getElementById('hud-in-cover');
  if (proxy) proxy.textContent = isFiniteNumber(item.vegetation_coverage_proxy_pct) ? `${item.vegetation_coverage_proxy_pct.toFixed(1)}%` : '—';

  if (currentPlotLayerKey !== 'esri') updateGeeOverlay();

  if (plotNdviChart) {
    const chartIndex = activePlot.timeseries.findIndex(seriesItem => seriesItem.month === item.month);
    if (chartIndex >= 0) {
      plotNdviChart.setActiveElements([{ datasetIndex: 0, index: chartIndex }]);
      plotNdviChart.update('none');
    }
  }
};

onMonthSliderChange = value => setMonthIndex(parseInt(value, 10));
prevMonth = () => setMonthIndex((currentMonthIndex - 1 + HOTFIX_DATES.length) % HOTFIX_DATES.length);
nextMonth = () => setMonthIndex((currentMonthIndex + 1) % HOTFIX_DATES.length);

initCompareSelectors = function(plot) {
  const left = document.getElementById('comp-left-select');
  const right = document.getElementById('comp-right-select');
  if (!left || !right) return;

  left.innerHTML = '';
  right.innerHTML = '';

  HOTFIX_DATES.forEach((monthKey, hotfixIndex) => {
    const item = plot.timeseries?.find(entry => entry.month === monthKey) || hotfixParseMonthKey(monthKey);
    const metric = isFiniteNumber(item.mean_ndvi_inside) ? ` • NDVI ${item.mean_ndvi_inside.toFixed(2)}` : '';
    const label = `${thaiMonths[item.month_num]} ${item.year}${metric}`;

    const l = document.createElement('option');
    l.value = String(hotfixIndex);
    l.textContent = label;
    left.appendChild(l);
    right.appendChild(l.cloneNode(true));
  });

  left.value = '0';
  right.value = String(HOTFIX_DATES.length - 1);
};

setPlotMapLayer = function(layerKey) {
  currentPlotLayerKey = layerKey;
  document.querySelectorAll('.band-btn-group .band-btn').forEach(button => {
    button.classList.toggle('active', button.dataset.layer === layerKey);
  });

  hotfixSentinelSwapToken++;

  if (layerKey === 'esri') {
    if (hotfixPendingSentinelOverlay && plotSatelliteMap?.hasLayer(hotfixPendingSentinelOverlay)) {
      plotSatelliteMap.removeLayer(hotfixPendingSentinelOverlay);
    }
    hotfixPendingSentinelOverlay = null;

    if (currentSentinelOverlay && plotSatelliteMap?.hasLayer(currentSentinelOverlay)) {
      plotSatelliteMap.removeLayer(currentSentinelOverlay);
    }
    currentSentinelOverlay = null;
    return;
  }

  updateGeeOverlay();
};

updateGeeOverlay = async function() {
  if (!activePlot || !plotSatelliteMap || currentPlotLayerKey === 'esri') return;

  const item = hotfixFindItem(currentMonthIndex);
  if (!item || !HOTFIX_DATES.includes(item.month)) return;

  const prefix = currentPlotLayerKey === 'gee_ndvi' ? 'ndvi' : 'rgb';
  const imageUrl = `data/plots/${activePlot.id}/${prefix}_${item.month}.png`;
  const requestToken = ++hotfixSentinelSwapToken;

  try {
    await hotfixPreloadImage(imageUrl);
  } catch (error) {
    if (requestToken !== hotfixSentinelSwapToken) return;
    const status = document.getElementById('hud-month-label');
    if (status) status.textContent = `${fullThaiMonths[item.month_num]} ${item.year} • ไม่มีภาพ`;
    return;
  }

  if (requestToken !== hotfixSentinelSwapToken || currentPlotLayerKey === 'esri') return;

  if (hotfixPendingSentinelOverlay && hotfixPendingSentinelOverlay !== currentSentinelOverlay && plotSatelliteMap.hasLayer(hotfixPendingSentinelOverlay)) {
    plotSatelliteMap.removeLayer(hotfixPendingSentinelOverlay);
  }

  const oldOverlay = currentSentinelOverlay;
  const versionedUrl = `${imageUrl}?v=${HOTFIX_BUILD}`;
  const newOverlay = L.imageOverlay(versionedUrl, imageBoundsForPlot(activePlot), {
    opacity: 0,
    interactive: false,
    className: 'sentinel-overlay'
  });

  hotfixPendingSentinelOverlay = newOverlay;

  newOverlay.once('load', () => {
    if (requestToken !== hotfixSentinelSwapToken) {
      if (plotSatelliteMap.hasLayer(newOverlay)) plotSatelliteMap.removeLayer(newOverlay);
      return;
    }

    requestAnimationFrame(() => newOverlay.setOpacity(1));

    setTimeout(() => {
      if (requestToken !== hotfixSentinelSwapToken) return;
      if (oldOverlay && oldOverlay !== newOverlay && plotSatelliteMap.hasLayer(oldOverlay)) {
        plotSatelliteMap.removeLayer(oldOverlay);
      }
      currentSentinelOverlay = newOverlay;
      hotfixPendingSentinelOverlay = null;
      if (plotBoundaryLayer) plotBoundaryLayer.bringToFront();
    }, 320);
  });

  newOverlay.once('error', () => {
    if (plotSatelliteMap.hasLayer(newOverlay)) plotSatelliteMap.removeLayer(newOverlay);
    if (hotfixPendingSentinelOverlay === newOverlay) hotfixPendingSentinelOverlay = null;
  });

  newOverlay.addTo(plotSatelliteMap);
  if (plotBoundaryLayer) plotBoundaryLayer.bringToFront();
};

ensureCompareMap = function() {
  if (compareMap) {
    if (hotfixCompareEsriBaseLayer && !compareMap.hasLayer(hotfixCompareEsriBaseLayer)) {
      hotfixCompareEsriBaseLayer.addTo(compareMap);
    }
    return;
  }

  const container = document.getElementById('compare-container');
  if (!container) return;

  container.innerHTML = `
    <div id="compare-leaflet-map" class="compare-leaflet-map"></div>
    <div class="compare-label left-label" id="comp-label-before">ก.ย. 2023</div>
    <div class="compare-label right-label" id="comp-label-after">ส.ค. 2026</div>
    <div class="compare-handle" id="comp-divider"><div class="handle-circle">↔</div></div>
    <div class="compare-no-data hidden" id="compare-no-data"></div>`;

  compareMap = L.map('compare-leaflet-map', {
    zoomControl: true,
    attributionControl: true,
    dragging: false,
    scrollWheelZoom: true,
    doubleClickZoom: true,
    boxZoom: false,
    keyboard: false
  }).setView([12.75, 101.80], 15);

  compareMap.createPane('compareEsriPane');
  compareMap.getPane('compareEsriPane').style.zIndex = 200;
  compareMap.createPane('compareAfterPane');
  compareMap.getPane('compareAfterPane').style.zIndex = 410;
  compareMap.createPane('compareBeforePane');
  compareMap.getPane('compareBeforePane').style.zIndex = 420;
  compareMap.createPane('compareBoundaryPane');
  compareMap.getPane('compareBoundaryPane').style.zIndex = 430;

  hotfixCompareEsriBaseLayer = L.tileLayer(ESRI_WORLD_IMAGERY, {
    pane: 'compareEsriPane',
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri'
  }).addTo(compareMap);

  setCompareDividerPosition(compareDividerPct);
};

const hotfixBaseUpdateCompareView = updateCompareView;
updateCompareView = function() {
  if (!activePlot) return;

  const originalTimeseries = activePlot.timeseries;
  activePlot.timeseries = HOTFIX_DATES.map(monthKey =>
    originalTimeseries.find(item => item.month === monthKey) || {
      ...hotfixParseMonthKey(monthKey),
      mean_ndvi_inside: null,
      vegetation_coverage_proxy_pct: null
    }
  );

  try {
    hotfixBaseUpdateCompareView();
    if (compareMap && hotfixCompareEsriBaseLayer && !compareMap.hasLayer(hotfixCompareEsriBaseLayer)) {
      hotfixCompareEsriBaseLayer.addTo(compareMap);
    }
  } finally {
    activePlot.timeseries = originalTimeseries;
  }
};

document.addEventListener('DOMContentLoaded', () => {
  hotfixForce12DateUi();
  setTimeout(hotfixForce12DateUi, 500);
  setTimeout(hotfixForce12DateUi, 1500);
});
