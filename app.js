// Prasae Mangrove Monitoring — geospatial integrity rewrite
// 12 observed/composite dates only. No interpolation and no synthetic statistics.

const MILESTONE_MONTHS = [
  '2023-09', '2023-12', '2024-03', '2024-06',
  '2024-09', '2024-12', '2025-03', '2025-06',
  '2025-09', '2025-12', '2026-03', '2026-08'
];

const thaiMonths = {
  1: 'ม.ค.', 2: 'ก.พ.', 3: 'มี.ค.', 4: 'เม.ย.',
  5: 'พ.ค.', 6: 'มิ.ย.', 7: 'ก.ค.', 8: 'ส.ค.',
  9: 'ก.ย.', 10: 'ต.ค.', 11: 'พ.ย.', 12: 'ธ.ค.'
};

const fullThaiMonths = {
  1: 'มกราคม', 2: 'กุมภาพันธ์', 3: 'มีนาคม', 4: 'เมษายน',
  5: 'พฤษภาคม', 6: 'มิถุนายน', 7: 'กรกฎาคม', 8: 'สิงหาคม',
  9: 'กันยายน', 10: 'ตุลาคม', 11: 'พฤศจิกายน', 12: 'ธันวาคม'
};

const ESRI_WORLD_IMAGERY = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const IMAGE_BUFFER_DEG = 0.003;
const VERIFIED_DATA_URL = 'data/timeseries_verified_12.json';

let plotsCatalog = [];
let allPlotsData = [];
let activePlot = null;
let currentMonthIndex = 0;
let currentPlotLayerKey = 'esri';
let verifiedDatasetLoaded = false;

let isPlaying = false;
let playInterval = null;
const playbackSpeed = 900;
let plotNdviChart = null;

let plotSatelliteMap = null;
let plotBoundaryLayer = null;
let currentSentinelOverlay = null;
let leafletMap = null;
let thailandGeojsonLayer = null;

let compareMap = null;
let compareBeforeOverlay = null;
let compareAfterOverlay = null;
let compareBoundaryLayer = null;
let compareDividerPct = 50;
let comparePlotId = null;

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function parseMonthKey(monthKey) {
  const [year, month] = monthKey.split('-').map(Number);
  return { month: monthKey, year, month_num: month };
}

function makePlaceholderPlot(plot) {
  return {
    ...plot,
    initial_ndvi: null,
    current_ndvi: null,
    gain_ndvi: null,
    growth_pct: null,
    current_vegetation_proxy_pct: null,
    data_quality: 'not_processed',
    timeseries: MILESTONE_MONTHS.map(month => ({
      ...parseMonthKey(month),
      mean_ndvi_inside: null,
      median_ndvi_inside: null,
      vegetation_coverage_proxy_pct: null,
      scenes_used: 0,
      clear_pixel_pct: null,
      status: 'not_processed',
      source: null,
      scene_ids: []
    }))
  };
}

function normalizePlot(plot, catalogPlot) {
  const base = { ...catalogPlot, ...plot };
  const byMonth = new Map((plot.timeseries || []).map(item => [item.month, item]));
  base.timeseries = MILESTONE_MONTHS.map(month => {
    const source = byMonth.get(month) || {};
    return {
      ...parseMonthKey(month),
      mean_ndvi_inside: isFiniteNumber(source.mean_ndvi_inside) ? source.mean_ndvi_inside : null,
      median_ndvi_inside: isFiniteNumber(source.median_ndvi_inside) ? source.median_ndvi_inside : null,
      vegetation_coverage_proxy_pct: isFiniteNumber(source.vegetation_coverage_proxy_pct)
        ? source.vegetation_coverage_proxy_pct
        : null,
      scenes_used: Number.isInteger(source.scenes_used) ? source.scenes_used : 0,
      clear_pixel_pct: isFiniteNumber(source.clear_pixel_pct) ? source.clear_pixel_pct : null,
      status: source.status || 'no_data',
      source: source.source || null,
      scene_ids: Array.isArray(source.scene_ids) ? source.scene_ids : []
    };
  });
  base.initial_ndvi = isFiniteNumber(plot.initial_ndvi) ? plot.initial_ndvi : null;
  base.current_ndvi = isFiniteNumber(plot.current_ndvi) ? plot.current_ndvi : null;
  base.gain_ndvi = isFiniteNumber(plot.gain_ndvi) ? plot.gain_ndvi : null;
  base.growth_pct = isFiniteNumber(plot.growth_pct) ? plot.growth_pct : null;
  base.current_vegetation_proxy_pct = isFiniteNumber(plot.current_vegetation_proxy_pct)
    ? plot.current_vegetation_proxy_pct
    : null;
  return base;
}

async function loadData() {
  const catalogResponse = await fetch('data/plots_catalog.json', { cache: 'no-store' });
  if (!catalogResponse.ok) throw new Error(`plots_catalog.json: HTTP ${catalogResponse.status}`);
  plotsCatalog = await catalogResponse.json();

  let verified = [];
  try {
    const verifiedResponse = await fetch(VERIFIED_DATA_URL, { cache: 'no-store' });
    if (verifiedResponse.ok) {
      const payload = await verifiedResponse.json();
      if (Array.isArray(payload)) verified = payload;
    }
  } catch (error) {
    console.warn('Verified dataset is not available yet:', error);
  }

  const verifiedById = new Map(verified.map(plot => [plot.id, plot]));
  verifiedDatasetLoaded = verified.length > 0;
  allPlotsData = plotsCatalog.map(plot => {
    const observed = verifiedById.get(plot.id);
    return observed ? normalizePlot(observed, plot) : makePlaceholderPlot(plot);
  });
}

function injectIntegrityStyles() {
  const style = document.createElement('style');
  style.textContent = `
    .leaflet-image-layer.sentinel-overlay { transition: opacity 280ms ease; }
    .integrity-chart-status {
      position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
      text-align:center; padding:1rem; color:#94a3b8; font-size:.82rem;
      background:rgba(15,23,42,.42); border-radius:8px; pointer-events:none;
    }
    .integrity-chart-status.hidden { display:none; }
    .compare-leaflet-map { position:absolute; inset:0; z-index:1; }
    .compare-stage .leaflet-control-container { position:relative; z-index:50; }
    .compare-stage .compare-label, .compare-stage .compare-handle { z-index:600; }
    .compare-no-data {
      position:absolute; left:50%; bottom:1rem; transform:translateX(-50%); z-index:650;
      background:rgba(15,23,42,.9); color:#cbd5e1; border:1px solid rgba(255,255,255,.12);
      border-radius:8px; padding:.4rem .7rem; font-size:.75rem; pointer-events:none;
    }
    .metric-unavailable { color:#94a3b8 !important; }
  `;
  document.head.appendChild(style);
}

function updateStaticCopy() {
  const plotCount = plotsCatalog.length;
  const provinceCount = new Set(plotsCatalog.map(plot => plot.province)).size;
  const totalArea = plotsCatalog.reduce((sum, plot) => sum + (Number(plot.area_rai) || 0), 0);

  const brandTitle = document.querySelector('.brand-title');
  if (brandTitle) brandTitle.textContent = `ระบบติดตามแปลงฟื้นฟูป่าชายเลน ${plotCount} แปลงทั่วประเทศ`;

  const brandSubtitle = document.querySelector('.brand-subtitle');
  if (brandSubtitle) brandSubtitle.textContent = 'Sentinel-2 L2A • 12 observation/composite dates • exact polygon clipping';

  const metaPills = document.querySelectorAll('.header-meta .meta-pill');
  if (metaPills[0]) metaPills[0].innerHTML = `<span class="pill-dot"></span> ${plotCount} แปลง (${totalArea.toLocaleString('th-TH', { maximumFractionDigits: 0 })} ไร่)`;
  const datePill = document.querySelector('.date-range-pill');
  if (datePill) datePill.textContent = '12 ช่วงเวลาภาพดาวเทียม';

  const totalAreaEl = document.getElementById('kpi-total-area');
  if (totalAreaEl) totalAreaEl.textContent = `${totalArea.toLocaleString('th-TH', { maximumFractionDigits: 0 })} ไร่`;
  const totalAreaSub = totalAreaEl?.parentElement?.querySelector('.kpi-sub');
  if (totalAreaSub) totalAreaSub.textContent = `ครอบคลุม ${provinceCount} จังหวัดในชุดข้อมูลปัจจุบัน`;

  const kpiCards = document.querySelectorAll('.national-kpi-grid .kpi-card');
  if (kpiCards[2]) {
    kpiCards[2].querySelector('.kpi-label').textContent = 'การเปลี่ยนแปลง NDVI (observed dates only)';
  }
  if (kpiCards[3]) {
    kpiCards[3].querySelector('.kpi-label').textContent = 'Vegetation coverage proxy';
    kpiCards[3].querySelector('.kpi-sub').textContent = 'สัดส่วนพิกเซลในแปลงที่ NDVI > 0.25; ไม่เรียกว่า canopy cover';
  }

  const detailTab = document.getElementById('wtab-detail');
  if (detailTab) detailTab.lastChild.textContent = ' วิเคราะห์ 12 ช่วงเวลา (Observed / Composite)';

  const chartTitle = document.getElementById('chart-plot-title');
  if (chartTitle) chartTitle.textContent = 'NDVI และ Vegetation Proxy — 12 observation/composite dates';
  const chartSubtitle = document.querySelector('.chart-box-subtitle');
  if (chartSubtitle) chartSubtitle.textContent = 'ไม่มีการ interpolate ระหว่างเดือน และไม่มี synthetic fallback; ช่องที่ไม่มี observation จะแสดงเป็น No data';
  const chartBadge = document.querySelector('.chart-badge-tag');
  if (chartBadge) chartBadge.textContent = verifiedDatasetLoaded ? 'Verified 12-date dataset' : 'Verified statistics pending';

  const rgbButton = document.querySelector('.band-btn[data-layer="gee_rgb"]');
  if (rgbButton) rgbButton.textContent = 'Sentinel-2 RGB (ในขอบเขตแปลง)';
  const ndviButton = document.querySelector('.band-btn[data-layer="gee_ndvi"]');
  if (ndviButton) ndviButton.textContent = 'NDVI (ในขอบเขตแปลง)';

  const hudTopRight = document.querySelector('.stage-hud.top-right');
  if (hudTopRight) hudTopRight.innerHTML = '<div class="hud-tag">Cloud-masked composite</div><div class="hud-sub">SCL QA • no interpolation</div>';
  const hudBottomLeft = document.querySelector('.stage-hud.bottom-left');
  if (hudBottomLeft) {
    const subs = hudBottomLeft.querySelectorAll('.hud-sub');
    if (subs[1]) subs[1].textContent = 'Sentinel-2 L2A clipped over Esri World Imagery';
  }
  const hudBottomRight = document.querySelector('.stage-hud.bottom-right');
  if (hudBottomRight) {
    hudBottomRight.innerHTML = '<div class="hud-pill">Mean NDVI: <strong id="hud-in-ndvi">—</strong></div><div class="hud-pill">Vegetation proxy: <strong id="hud-in-cover">—</strong></div>';
  }

  const slider = document.getElementById('month-slider');
  if (slider) {
    slider.max = String(MILESTONE_MONTHS.length - 1);
    slider.value = '0';
  }
  const ticks = document.querySelector('.slider-ticks');
  if (ticks) ticks.innerHTML = '<span>ก.ย. 2023</span><span>ก.ย. 2024</span><span>ก.ย. 2025</span><span>ส.ค. 2026</span>';

  const tableHeaders = document.querySelectorAll('#plots-data-table thead th');
  if (tableHeaders[7]) tableHeaders[7].textContent = 'Vegetation proxy (%)';

  const compareHint = document.querySelector('.compare-hint');
  if (compareHint) compareHint.textContent = 'ลากเส้นกลางเพื่อเปรียบเทียบ 2 observation dates; Esri เป็น basemap และ Sentinel-2 แสดงเฉพาะในขอบเขตแปลง';
}

function initProvinceFilter() {
  const select = document.getElementById('province-filter');
  select.innerHTML = `<option value="ALL">ทุกจังหวัด (ทั้งหมด ${plotsCatalog.length} แปลง)</option>`;
  const provinces = [...new Set(plotsCatalog.map(plot => plot.province))].sort();
  provinces.forEach(province => {
    const option = document.createElement('option');
    option.value = province;
    option.textContent = `${province} (${plotsCatalog.filter(plot => plot.province === province).length} แปลง)`;
    select.appendChild(option);
  });
}

function onProvinceFilterChange(province) {
  const query = document.getElementById('plot-search-input').value.toLowerCase().trim();
  filterPlots(province, query);
}

function onPlotSearchInput(query) {
  const province = document.getElementById('province-filter').value;
  filterPlots(province, query.toLowerCase().trim());
}

function filterPlots(province, query) {
  let filtered = allPlotsData;
  if (province !== 'ALL') filtered = filtered.filter(plot => plot.province === province);
  if (query) {
    filtered = filtered.filter(plot =>
      plot.name.toLowerCase().includes(query) ||
      plot.code.toLowerCase().includes(query) ||
      plot.province.toLowerCase().includes(query)
    );
  }
  renderSidebarList(filtered);
}

function renderSidebarList(plots) {
  const container = document.getElementById('plot-list-container');
  document.getElementById('sidebar-count-display').textContent = `แสดง ${plots.length} จาก ${allPlotsData.length} แปลง`;
  container.innerHTML = '';

  plots.forEach(plot => {
    const hasGain = isFiniteNumber(plot.gain_ndvi);
    const card = document.createElement('div');
    card.className = `plot-card-item ${activePlot?.id === plot.id ? 'active' : ''}`;
    card.id = `sidebar-card-${plot.id}`;
    card.onclick = () => selectPlot(plot.id);
    card.innerHTML = `
      <div class="p-card-header">
        <span class="p-card-title" title="${escapeHtml(plot.name)}">${escapeHtml(plot.name)}</span>
        <span class="p-prov-tag">${escapeHtml(plot.province)}</span>
      </div>
      <div class="p-card-body">
        <span>เนื้อที่: <strong>${Number(plot.area_rai).toFixed(1)} ไร่</strong></span>
        <span>${hasGain ? `NDVI: <strong class="ndvi-gain">${plot.gain_ndvi >= 0 ? '+' : ''}${plot.gain_ndvi.toFixed(3)}</strong>` : '<strong>12 dates • รอ verified stats</strong>'}</span>
      </div>`;
    container.appendChild(card);
  });
}

function initPlotSatelliteMap() {
  plotSatelliteMap = L.map('plot-satellite-map', {
    zoomControl: true,
    attributionControl: true
  }).setView([12.75, 101.80], 15);

  L.tileLayer(ESRI_WORLD_IMAGERY, {
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri'
  }).addTo(plotSatelliteMap);
}

function imageBoundsForPlot(plot) {
  const bounds = plot.bounds;
  return [
    [bounds[1] - IMAGE_BUFFER_DEG, bounds[0] - IMAGE_BUFFER_DEG],
    [bounds[3] + IMAGE_BUFFER_DEG, bounds[2] + IMAGE_BUFFER_DEG]
  ];
}

function updatePlotSatelliteViewer(plot) {
  if (!plotSatelliteMap || !plot.geometry) return;
  if (plotBoundaryLayer) plotSatelliteMap.removeLayer(plotBoundaryLayer);

  plotBoundaryLayer = L.geoJSON({
    type: 'Feature', properties: { id: plot.id, name: plot.name }, geometry: plot.geometry
  }, {
    style: {
      color: '#34d399',
      weight: 2,
      opacity: 1,
      fillOpacity: 0
    }
  }).addTo(plotSatelliteMap);

  const bounds = plotBoundaryLayer.getBounds();
  if (bounds.isValid()) {
    plotSatelliteMap.fitBounds(bounds, { padding: [45, 45], maxZoom: 17, animate: false });
  }

  togglePlotBoundary(document.getElementById('toggle-boundary-check')?.checked !== false);
}

function setPlotMapLayer(layerKey) {
  currentPlotLayerKey = layerKey;
  document.querySelectorAll('.band-btn-group .band-btn').forEach(button => {
    button.classList.toggle('active', button.dataset.layer === layerKey);
  });

  if (layerKey === 'esri') {
    if (currentSentinelOverlay && plotSatelliteMap.hasLayer(currentSentinelOverlay)) {
      plotSatelliteMap.removeLayer(currentSentinelOverlay);
    }
    currentSentinelOverlay = null;
    return;
  }
  updateGeeOverlay();
}

function updateGeeOverlay() {
  if (!activePlot || !plotSatelliteMap || currentPlotLayerKey === 'esri') return;
  const item = activePlot.timeseries[currentMonthIndex];
  if (!item) return;

  const prefix = currentPlotLayerKey === 'gee_ndvi' ? 'ndvi' : 'rgb';
  const imageUrl = `data/plots/${activePlot.id}/${prefix}_${item.month}.png`;
  const oldOverlay = currentSentinelOverlay;
  const newOverlay = L.imageOverlay(imageUrl, imageBoundsForPlot(activePlot), {
    opacity: 0,
    interactive: false,
    className: 'sentinel-overlay'
  });

  newOverlay.on('load', () => {
    requestAnimationFrame(() => newOverlay.setOpacity(1));
    if (oldOverlay && oldOverlay !== newOverlay && plotSatelliteMap.hasLayer(oldOverlay)) {
      setTimeout(() => {
        if (plotSatelliteMap.hasLayer(oldOverlay)) plotSatelliteMap.removeLayer(oldOverlay);
      }, 300);
    }
  });

  newOverlay.on('error', () => {
    if (plotSatelliteMap.hasLayer(newOverlay)) plotSatelliteMap.removeLayer(newOverlay);
    const status = document.getElementById('hud-month-label');
    if (status) status.textContent = `${fullThaiMonths[item.month_num]} ${item.year} • ไม่มีภาพ`;
  });

  newOverlay.addTo(plotSatelliteMap);
  currentSentinelOverlay = newOverlay;
  if (plotBoundaryLayer) plotBoundaryLayer.bringToFront();
}

function togglePlotBoundary(show) {
  if (!plotSatelliteMap || !plotBoundaryLayer) return;
  if (show && !plotSatelliteMap.hasLayer(plotBoundaryLayer)) plotBoundaryLayer.addTo(plotSatelliteMap);
  if (!show && plotSatelliteMap.hasLayer(plotBoundaryLayer)) plotSatelliteMap.removeLayer(plotBoundaryLayer);
  if (show) plotBoundaryLayer.bringToFront();
}

function renderPlotChart(plot) {
  const series = plot.timeseries;
  const ndviData = series.map(item => item.mean_ndvi_inside);
  const proxyData = series.map(item => item.vegetation_coverage_proxy_pct);
  const hasAnyMetric = ndviData.some(isFiniteNumber) || proxyData.some(isFiniteNumber);

  if (plotNdviChart) plotNdviChart.destroy();
  const container = document.querySelector('.chart-canvas-container');
  let status = container.querySelector('.integrity-chart-status');
  if (!status) {
    status = document.createElement('div');
    status.className = 'integrity-chart-status';
    container.appendChild(status);
  }
  status.classList.toggle('hidden', hasAnyMetric);
  status.textContent = 'ยังไม่มี verified 12-date statistics สำหรับชุดนี้ — ภาพดาวเทียมยังดูได้ แต่ระบบไม่ใช้ค่า interpolated/synthetic เดิม';

  const ctx = document.getElementById('plotNdviChart').getContext('2d');
  plotNdviChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: series.map(item => `${thaiMonths[item.month_num]} ${String(item.year).slice(2)}`),
      datasets: [
        {
          label: 'Mean NDVI (observed/composite)',
          data: ndviData,
          borderColor: '#10b981',
          backgroundColor: 'rgba(16,185,129,.10)',
          borderWidth: 2.5,
          pointRadius: 4,
          pointHoverRadius: 7,
          tension: 0,
          spanGaps: false,
          yAxisID: 'y'
        },
        {
          label: 'Vegetation coverage proxy (NDVI > 0.25)',
          data: proxyData,
          borderColor: '#38bdf8',
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 6,
          tension: 0,
          spanGaps: false,
          yAxisID: 'y1'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      onClick: (event, elements) => {
        if (elements?.length) setMonthIndex(elements[0].index);
      },
      plugins: {
        legend: { labels: { color: '#94a3b8', font: { family: 'Plus Jakarta Sans', size: 11 } } },
        tooltip: {
          callbacks: {
            afterBody: contexts => {
              if (!contexts?.length) return '';
              const item = series[contexts[0].dataIndex];
              const clear = isFiniteNumber(item.clear_pixel_pct) ? `${item.clear_pixel_pct.toFixed(1)}% clear pixels` : 'clear-pixel QA unavailable';
              return `${item.scenes_used || 0} scene(s) • ${clear} • ${item.status}`;
            }
          }
        }
      },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,.05)' }, ticks: { color: '#64748b' } },
        y: {
          min: -0.1, max: 0.9, position: 'left',
          title: { display: true, text: 'Mean NDVI', color: '#10b981' },
          grid: { color: 'rgba(255,255,255,.05)' }, ticks: { color: '#94a3b8' }
        },
        y1: {
          min: 0, max: 100, position: 'right',
          title: { display: true, text: 'Vegetation proxy (%)', color: '#38bdf8' },
          grid: { drawOnChartArea: false }, ticks: { color: '#94a3b8', callback: value => `${value}%` }
        }
      }
    }
  });
}

function selectPlot(plotId) {
  const plot = allPlotsData.find(item => item.id === plotId);
  if (!plot) return;
  activePlot = plot;
  currentMonthIndex = Math.min(currentMonthIndex, MILESTONE_MONTHS.length - 1);

  document.querySelectorAll('.plot-card-item').forEach(card => card.classList.remove('active'));
  const activeCard = document.getElementById(`sidebar-card-${plot.id}`);
  if (activeCard) {
    activeCard.classList.add('active');
    activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  document.getElementById('kpi-current-plot-name').textContent = plot.name;
  document.getElementById('kpi-current-plot-sub').textContent = `เนื้อที่ ${Number(plot.area_rai).toFixed(1)} ไร่ • ${plot.centroid[0].toFixed(4)}°N, ${plot.centroid[1].toFixed(4)}°E (${plot.province})`;

  const gainEl = document.getElementById('kpi-plot-ndvi-gain');
  const gainSub = document.getElementById('kpi-plot-gain-pct');
  if (isFiniteNumber(plot.gain_ndvi)) {
    gainEl.textContent = `${plot.gain_ndvi >= 0 ? '+' : ''}${plot.gain_ndvi.toFixed(3)}`;
    gainEl.classList.remove('metric-unavailable');
    gainSub.textContent = isFiniteNumber(plot.growth_pct) ? `${plot.growth_pct >= 0 ? '+' : ''}${plot.growth_pct.toFixed(1)}% จาก observed endpoints` : 'คำนวณจาก observed endpoints';
  } else {
    gainEl.textContent = '—';
    gainEl.classList.add('metric-unavailable');
    gainSub.textContent = 'ยังไม่มี verified statistic; ไม่ใช้ค่า interpolated/synthetic เดิม';
  }

  const proxyEl = document.getElementById('kpi-plot-canopy-pct');
  proxyEl.textContent = isFiniteNumber(plot.current_vegetation_proxy_pct) ? `${plot.current_vegetation_proxy_pct.toFixed(1)}%` : '—';
  proxyEl.classList.toggle('metric-unavailable', !isFiniteNumber(plot.current_vegetation_proxy_pct));

  document.getElementById('chart-plot-title').textContent = `NDVI และ Vegetation Proxy — ${plot.name}`;
  renderPlotChart(plot);
  updatePlotSatelliteViewer(plot);
  setMonthIndex(currentMonthIndex);
  initCompareSelectors(plot);

  if (leafletMap && thailandGeojsonLayer) {
    thailandGeojsonLayer.eachLayer(layer => {
      const selected = layer.feature?.properties?.id === plot.id;
      layer.setStyle({
        color: selected ? '#38bdf8' : '#10b981',
        weight: selected ? 4 : 2,
        fillOpacity: selected ? 0.12 : 0.04
      });
      if (selected) layer.bringToFront();
    });
  }
}

function setMonthIndex(index) {
  if (!activePlot) return;
  const idx = Math.max(0, Math.min(MILESTONE_MONTHS.length - 1, Number(index)));
  currentMonthIndex = idx;
  const item = activePlot.timeseries[idx];

  document.getElementById('month-slider').value = String(idx);
  document.getElementById('playback-date-display').textContent = `${thaiMonths[item.month_num]} ${item.year}`;
  document.getElementById('hud-month-label').textContent = `${fullThaiMonths[item.month_num]} ${item.year}`;
  document.getElementById('hud-plot-label').textContent = `${activePlot.name} (${activePlot.province})`;
  document.getElementById('hud-coords-label').textContent = `${activePlot.centroid[0].toFixed(4)}°N, ${activePlot.centroid[1].toFixed(4)}°E • ${Number(activePlot.area_rai).toFixed(1)} ไร่`;
  document.getElementById('hud-in-ndvi').textContent = isFiniteNumber(item.mean_ndvi_inside) ? item.mean_ndvi_inside.toFixed(3) : '—';
  document.getElementById('hud-in-cover').textContent = isFiniteNumber(item.vegetation_coverage_proxy_pct) ? `${item.vegetation_coverage_proxy_pct.toFixed(1)}%` : '—';

  if (currentPlotLayerKey !== 'esri') updateGeeOverlay();
  if (plotNdviChart) {
    plotNdviChart.setActiveElements([{ datasetIndex: 0, index: idx }]);
    plotNdviChart.update('none');
  }
}

function onMonthSliderChange(value) { setMonthIndex(parseInt(value, 10)); }
function prevMonth() { setMonthIndex((currentMonthIndex - 1 + MILESTONE_MONTHS.length) % MILESTONE_MONTHS.length); }
function nextMonth() { setMonthIndex((currentMonthIndex + 1) % MILESTONE_MONTHS.length); }

function togglePlay() { isPlaying ? pause() : play(); }
function play() {
  isPlaying = true;
  document.getElementById('play-icon').classList.add('hidden');
  document.getElementById('pause-icon').classList.remove('hidden');
  playInterval = setInterval(nextMonth, playbackSpeed);
}
function pause() {
  isPlaying = false;
  document.getElementById('play-icon').classList.remove('hidden');
  document.getElementById('pause-icon').classList.add('hidden');
  if (playInterval) clearInterval(playInterval);
  playInterval = null;
}

function initLeafletThailandMap() {
  leafletMap = L.map('thailand-map').setView([10.5, 100.5], 6);
  L.tileLayer(ESRI_WORLD_IMAGERY, { maxZoom: 19, attribution: 'Tiles &copy; Esri' }).addTo(leafletMap);

  fetch('data/plots.geojson')
    .then(response => response.json())
    .then(geojson => {
      thailandGeojsonLayer = L.geoJSON(geojson, {
        style: { color: '#10b981', weight: 2, opacity: .95, fillColor: '#10b981', fillOpacity: .04 },
        onEachFeature: (feature, layer) => {
          const properties = feature.properties;
          layer.bindPopup(`
            <div class="popup-title">${escapeHtml(properties.name)}</div>
            <div class="popup-meta">จังหวัด: <strong>${escapeHtml(properties.province)}</strong> | เนื้อที่: <strong>${Number(properties.area_rai).toFixed(1)} ไร่</strong></div>
            <button class="popup-btn" onclick="selectPlot(${properties.id}); switchWorkspaceTab('detail');">ดูแปลงนี้</button>`);
          layer.on('click', () => selectPlot(properties.id));
        }
      }).addTo(leafletMap);
    })
    .catch(error => console.error('Cannot load plots.geojson:', error));
}

function resetMapZoom() {
  if (leafletMap) leafletMap.setView([10.5, 100.5], 6);
}

function switchWorkspaceTab(tab) {
  document.querySelectorAll('.w-tab-btn').forEach(button => button.classList.remove('active'));
  document.querySelectorAll('.tab-content-panel').forEach(panel => panel.classList.remove('active'));
  document.getElementById(`wtab-${tab}`).classList.add('active');
  document.getElementById(`panel-${tab}`).classList.add('active');

  if (tab === 'detail' && plotSatelliteMap) {
    setTimeout(() => {
      plotSatelliteMap.invalidateSize();
      if (activePlot) updatePlotSatelliteViewer(activePlot);
    }, 100);
  }
  if (tab === 'map' && leafletMap) setTimeout(() => leafletMap.invalidateSize(), 100);
  if (tab === 'compare') {
    setTimeout(() => {
      updateCompareView();
      if (compareMap) compareMap.invalidateSize();
    }, 100);
  }
}

function initCompareSelectors(plot) {
  const left = document.getElementById('comp-left-select');
  const right = document.getElementById('comp-right-select');
  left.innerHTML = '';
  right.innerHTML = '';

  plot.timeseries.forEach((item, index) => {
    const metric = isFiniteNumber(item.mean_ndvi_inside) ? ` • NDVI ${item.mean_ndvi_inside.toFixed(2)}` : '';
    const label = `${thaiMonths[item.month_num]} ${item.year}${metric}`;
    const optionLeft = document.createElement('option');
    optionLeft.value = String(index);
    optionLeft.textContent = label;
    left.appendChild(optionLeft);
    const optionRight = optionLeft.cloneNode(true);
    right.appendChild(optionRight);
  });
  left.value = '0';
  right.value = String(MILESTONE_MONTHS.length - 1);
}

function ensureCompareMap() {
  if (compareMap) return;
  const container = document.getElementById('compare-container');
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

  L.tileLayer(ESRI_WORLD_IMAGERY, { maxZoom: 19, attribution: 'Tiles &copy; Esri' }).addTo(compareMap);

  compareMap.createPane('compareAfterPane');
  compareMap.getPane('compareAfterPane').style.zIndex = 410;
  compareMap.createPane('compareBeforePane');
  compareMap.getPane('compareBeforePane').style.zIndex = 420;
  compareMap.createPane('compareBoundaryPane');
  compareMap.getPane('compareBoundaryPane').style.zIndex = 430;
  setCompareDividerPosition(compareDividerPct);
}

function setCompareDividerPosition(percent) {
  compareDividerPct = Math.max(0, Math.min(100, percent));
  const pane = compareMap?.getPane('compareBeforePane');
  if (pane) pane.style.clipPath = `inset(0 ${100 - compareDividerPct}% 0 0)`;
  const divider = document.getElementById('comp-divider');
  if (divider) divider.style.left = `${compareDividerPct}%`;
}

function initCompareSlider() {
  const container = document.getElementById('compare-container');
  if (!container || container.dataset.sliderInit === 'true') return;
  container.dataset.sliderInit = 'true';
  let dragging = false;

  const update = event => {
    if (!dragging) return;
    event.preventDefault();
    const rect = container.getBoundingClientRect();
    const clientX = event.touches?.[0]?.clientX ?? event.clientX;
    setCompareDividerPosition(((clientX - rect.left) / rect.width) * 100);
  };
  container.addEventListener('mousedown', event => { dragging = true; update(event); });
  container.addEventListener('touchstart', event => { dragging = true; update(event); }, { passive: false });
  window.addEventListener('mousemove', update);
  window.addEventListener('touchmove', update, { passive: false });
  window.addEventListener('mouseup', () => { dragging = false; });
  window.addEventListener('touchend', () => { dragging = false; });
}

function replaceCompareOverlay(existing, url, plot, pane) {
  if (existing && compareMap.hasLayer(existing)) compareMap.removeLayer(existing);
  const overlay = L.imageOverlay(url, imageBoundsForPlot(plot), {
    opacity: 1,
    interactive: false,
    pane,
    className: 'sentinel-overlay'
  }).addTo(compareMap);
  overlay.on('error', () => {
    const notice = document.getElementById('compare-no-data');
    if (notice) {
      notice.textContent = 'มี observation date แต่ไม่มีไฟล์ภาพสำหรับช่วงเวลานี้';
      notice.classList.remove('hidden');
    }
  });
  return overlay;
}

function updateCompareView() {
  if (!activePlot) return;
  ensureCompareMap();
  initCompareSlider();

  const leftIndex = parseInt(document.getElementById('comp-left-select').value || '0', 10);
  const rightIndex = parseInt(document.getElementById('comp-right-select').value || String(MILESTONE_MONTHS.length - 1), 10);
  const mode = document.getElementById('comp-mode-select')?.value || 'rgb';
  const leftItem = activePlot.timeseries[leftIndex];
  const rightItem = activePlot.timeseries[rightIndex];
  if (!leftItem || !rightItem) return;

  let leftPrefix = 'rgb';
  let rightPrefix = 'rgb';
  if (mode === 'ndvi') leftPrefix = rightPrefix = 'ndvi';
  if (mode === 'rgb_vs_ndvi') rightPrefix = 'ndvi';

  document.getElementById('comp-label-before').textContent = `${thaiMonths[leftItem.month_num]} ${leftItem.year}${leftPrefix === 'ndvi' ? ' • NDVI' : ' • RGB'}`;
  document.getElementById('comp-label-after').textContent = `${thaiMonths[rightItem.month_num]} ${rightItem.year}${rightPrefix === 'ndvi' ? ' • NDVI' : ' • RGB'}`;
  document.getElementById('compare-no-data')?.classList.add('hidden');

  compareBeforeOverlay = replaceCompareOverlay(compareBeforeOverlay, `data/plots/${activePlot.id}/${leftPrefix}_${leftItem.month}.png`, activePlot, 'compareBeforePane');
  compareAfterOverlay = replaceCompareOverlay(compareAfterOverlay, `data/plots/${activePlot.id}/${rightPrefix}_${rightItem.month}.png`, activePlot, 'compareAfterPane');

  if (compareBoundaryLayer && compareMap.hasLayer(compareBoundaryLayer)) compareMap.removeLayer(compareBoundaryLayer);
  compareBoundaryLayer = L.geoJSON({ type: 'Feature', properties: {}, geometry: activePlot.geometry }, {
    pane: 'compareBoundaryPane',
    style: { color: '#34d399', weight: 2, opacity: 1, fillOpacity: 0 }
  }).addTo(compareMap);

  if (comparePlotId !== activePlot.id) {
    comparePlotId = activePlot.id;
    compareMap.fitBounds(compareBoundaryLayer.getBounds(), { padding: [40, 40], maxZoom: 17, animate: false });
  }
  setCompareDividerPosition(compareDividerPct);
  toggleCompareBoundary(document.getElementById('comp-boundary-toggle')?.checked !== false);

  const leftNdvi = leftItem.mean_ndvi_inside;
  const rightNdvi = rightItem.mean_ndvi_inside;
  const statText = document.getElementById('comp-in-stat-text');
  const gainPill = document.getElementById('comp-gain-pill');
  if (isFiniteNumber(leftNdvi) && isFiniteNumber(rightNdvi)) {
    const diff = rightNdvi - leftNdvi;
    statText.innerHTML = `Mean NDVI: <strong>${leftNdvi.toFixed(3)}</strong> ➔ <strong>${rightNdvi.toFixed(3)}</strong>`;
    gainPill.textContent = `${diff >= 0 ? '+' : ''}${diff.toFixed(3)}`;
  } else {
    statText.textContent = 'Verified NDVI statistics ยังไม่ถูกสร้าง — compare ภาพได้ แต่ไม่แสดงตัวเลขเดิม';
    gainPill.textContent = 'No verified metric';
  }
}

function toggleCompareBoundary(show) {
  if (!compareMap || !compareBoundaryLayer) return;
  if (show && !compareMap.hasLayer(compareBoundaryLayer)) compareBoundaryLayer.addTo(compareMap);
  if (!show && compareMap.hasLayer(compareBoundaryLayer)) compareMap.removeLayer(compareBoundaryLayer);
}

function initTable(plots) {
  const tbody = document.getElementById('table-body');
  document.getElementById('table-count-label').textContent = `แสดงทั้งหมด ${plots.length} แปลง`;
  tbody.innerHTML = '';
  plots.forEach(plot => {
    const row = document.createElement('tr');
    const gain = isFiniteNumber(plot.gain_ndvi) ? `${plot.gain_ndvi >= 0 ? '+' : ''}${plot.gain_ndvi.toFixed(3)}` : '—';
    row.innerHTML = `
      <td><strong>${escapeHtml(plot.code)}</strong></td>
      <td>${escapeHtml(plot.name)}</td>
      <td><span class="p-prov-tag">${escapeHtml(plot.province)}</span></td>
      <td>${Number(plot.area_rai).toFixed(1)}</td>
      <td>${isFiniteNumber(plot.initial_ndvi) ? plot.initial_ndvi.toFixed(3) : '—'}</td>
      <td>${isFiniteNumber(plot.current_ndvi) ? plot.current_ndvi.toFixed(3) : '—'}</td>
      <td><strong>${gain}</strong></td>
      <td>${isFiniteNumber(plot.current_vegetation_proxy_pct) ? plot.current_vegetation_proxy_pct.toFixed(1) : '—'}</td>
      <td><button class="btn-table-view" onclick="selectPlot(${plot.id}); switchWorkspaceTab('detail');">ดูรายละเอียด</button></td>`;
    tbody.appendChild(row);
  });
}

function exportPlotsCSV() {
  if (!allPlotsData.length) return;
  const headers = [
    'Plot ID', 'Plot Code', 'Plot Name', 'Province', 'Area (Rai)',
    'Initial NDVI (Sep 2023)', 'Current NDVI (Aug 2026)', 'NDVI Gain',
    'Vegetation Coverage Proxy %', 'Dataset Quality', 'Centroid Lat', 'Centroid Lon'
  ];
  const value = item => isFiniteNumber(item) ? item : '';
  const rows = allPlotsData.map(plot => [
    plot.id, `"${String(plot.code).replaceAll('"', '""')}"`, `"${String(plot.name).replaceAll('"', '""')}"`,
    `"${String(plot.province).replaceAll('"', '""')}"`, Number(plot.area_rai).toFixed(2),
    value(plot.initial_ndvi), value(plot.current_ndvi), value(plot.gain_ndvi),
    value(plot.current_vegetation_proxy_pct), verifiedDatasetLoaded ? 'verified_12_date_pipeline' : 'not_processed',
    plot.centroid[0], plot.centroid[1]
  ]);
  const csv = '\uFEFF' + [headers.join(','), ...rows.map(row => row.join(','))].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `mangrove_verified_12_dates_${new Date().toISOString().slice(0, 10)}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function init() {
  try {
    injectIntegrityStyles();
    await loadData();
    updateStaticCopy();
    initProvinceFilter();
    renderSidebarList(allPlotsData);
    initPlotSatelliteMap();
    initLeafletThailandMap();
    initTable(allPlotsData);
    initCompareSlider();

    const defaultPlot = allPlotsData.find(plot => plot.province === 'ระยอง') || allPlotsData[0];
    if (defaultPlot) selectPlot(defaultPlot.id);
  } catch (error) {
    console.error('Initialization error:', error);
    const workspace = document.querySelector('.workspace-area');
    if (workspace) workspace.insertAdjacentHTML('afterbegin', `<div class="chart-box">โหลดข้อมูลไม่สำเร็จ: ${escapeHtml(error.message)}</div>`);
  }
}

document.addEventListener('DOMContentLoaded', init);
