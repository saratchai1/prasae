// Prasae Mangrove Monitoring — stable 12-date viewer
const MILESTONE_MONTHS = [
  '2023-09', '2023-12', '2024-03', '2024-06',
  '2024-09', '2024-12', '2025-03', '2025-06',
  '2025-09', '2025-12', '2026-03', '2026-08'
];

const thaiMonths = {
  1:'ม.ค.',2:'ก.พ.',3:'มี.ค.',4:'เม.ย.',5:'พ.ค.',6:'มิ.ย.',
  7:'ก.ค.',8:'ส.ค.',9:'ก.ย.',10:'ต.ค.',11:'พ.ย.',12:'ธ.ค.'
};
const fullThaiMonths = {
  1:'มกราคม',2:'กุมภาพันธ์',3:'มีนาคม',4:'เมษายน',5:'พฤษภาคม',6:'มิถุนายน',
  7:'กรกฎาคม',8:'สิงหาคม',9:'กันยายน',10:'ตุลาคม',11:'พฤศจิกายน',12:'ธันวาคม'
};

const ESRI_WORLD_IMAGERY =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const IMAGE_BUFFER_DEG = 0.003;
const VERIFIED_DATA_URL = 'data/timeseries_verified_12.json';
const ASSET_VERSION = '20260817-2309';

let plotsCatalog = [];
let allPlotsData = [];
let activePlot = null;
let currentMonthIndex = 0;
let currentPlotLayerKey = 'esri';
let verifiedDatasetLoaded = false;

let isPlaying = false;
let playInterval = null;
const playbackSpeed = 1000;
let plotNdviChart = null;

let plotSatelliteMap = null;
let plotBoundaryLayer = null;
let currentSentinelOverlay = null;
let pendingSentinelOverlay = null;
let sentinelSwapToken = 0;

let leafletMap = null;
let thailandGeojsonLayer = null;

let compareLeftMap = null;
let compareRightMap = null;
let compareLeftOverlay = null;
let compareRightOverlay = null;
let compareLeftBoundary = null;
let compareRightBoundary = null;
let comparePlotId = null;

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&','&amp;')
    .replaceAll('<','&lt;')
    .replaceAll('>','&gt;')
    .replaceAll('"','&quot;')
    .replaceAll("'",'&#039;');
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
        ? source.vegetation_coverage_proxy_pct : null,
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
    ? plot.current_vegetation_proxy_pct : null;
  return base;
}

async function loadData() {
  const catalogResponse = await fetch(`data/plots_catalog.json?v=${ASSET_VERSION}`, { cache: 'no-store' });
  if (!catalogResponse.ok) throw new Error(`plots_catalog.json: HTTP ${catalogResponse.status}`);
  plotsCatalog = await catalogResponse.json();

  let verified = [];
  try {
    const response = await fetch(`${VERIFIED_DATA_URL}?v=${ASSET_VERSION}`, { cache: 'no-store' });
    if (response.ok) {
      const payload = await response.json();
      if (Array.isArray(payload)) verified = payload;
    }
  } catch (error) {
    console.warn('Verified dataset unavailable:', error);
  }

  const byId = new Map(verified.map(plot => [plot.id, plot]));
  verifiedDatasetLoaded = verified.length > 0;
  allPlotsData = plotsCatalog.map(plot => byId.has(plot.id)
    ? normalizePlot(byId.get(plot.id), plot)
    : makePlaceholderPlot(plot));
}

function injectRuntimeStyles() {
  const style = document.createElement('style');
  style.textContent = `
    .leaflet-image-layer.sentinel-overlay { transition: opacity 260ms ease; }
    .integrity-chart-status {
      position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
      text-align:center; padding:1rem; color:#94a3b8; font-size:.82rem;
      background:rgba(15,23,42,.42); border-radius:8px; pointer-events:none;
    }
    .integrity-chart-status.hidden { display:none; }
    .metric-unavailable { color:#94a3b8 !important; }
    .compare-stage {
      display:grid !important;
      grid-template-columns:minmax(0,1fr) minmax(0,1fr);
      gap:8px;
      position:relative;
      height:560px;
      min-height:420px;
      cursor:default !important;
      background:#0b1120;
    }
    .compare-map-panel {
      position:relative;
      min-width:0;
      height:100%;
      overflow:hidden;
      border-radius:10px;
    }
    .compare-leaflet-half { position:absolute; inset:0; }
    .compare-side-label {
      position:absolute; top:12px; left:12px; z-index:600;
      background:rgba(15,23,42,.9); border:1px solid rgba(255,255,255,.15);
      border-radius:8px; padding:7px 10px; color:#fff; font-size:.78rem;
      font-weight:700; pointer-events:none;
    }
    .compare-center-divider {
      position:absolute; left:50%; top:0; bottom:0; width:2px; transform:translateX(-1px);
      background:rgba(255,255,255,.55); z-index:650; pointer-events:none;
    }
    @media (max-width:900px) {
      .compare-stage { grid-template-columns:1fr; height:820px; }
      .compare-center-divider { display:none; }
    }
  `;
  document.head.appendChild(style);
}

function updateStaticCopy() {
  const plotCount = plotsCatalog.length;
  const provinceCount = new Set(plotsCatalog.map(plot => plot.province)).size;
  const totalArea = plotsCatalog.reduce((sum, plot) => sum + (Number(plot.area_rai) || 0), 0);

  const brandTitle = document.querySelector('.brand-title');
  if (brandTitle) brandTitle.textContent = `ระบบติดตามแปลงฟื้นฟูป่าชายเลน ${plotCount} แปลงทั่วประเทศ`;

  const metaPills = document.querySelectorAll('.header-meta .meta-pill');
  if (metaPills[0]) {
    metaPills[0].innerHTML = `<span class="pill-dot"></span> ${plotCount} แปลง (${totalArea.toLocaleString('th-TH',{maximumFractionDigits:0})} ไร่)`;
  }

  const totalAreaEl = document.getElementById('kpi-total-area');
  if (totalAreaEl) totalAreaEl.textContent = `${totalArea.toLocaleString('th-TH',{maximumFractionDigits:0})} ไร่`;

  const totalAreaSub = totalAreaEl?.parentElement?.querySelector('.kpi-sub');
  if (totalAreaSub) totalAreaSub.textContent = `ครอบคลุม ${provinceCount} จังหวัดในชุดข้อมูลปัจจุบัน`;

  const chartBadge = document.querySelector('.chart-badge-tag');
  if (chartBadge) chartBadge.textContent = verifiedDatasetLoaded ? 'Verified 12-date dataset' : 'Verified statistics pending';

  const slider = document.getElementById('month-slider');
  if (slider) {
    slider.min = '0';
    slider.max = '11';
    slider.step = '1';
    slider.value = '0';
  }
}

function initProvinceFilter() {
  const select = document.getElementById('province-filter');
  select.innerHTML = `<option value="ALL">ทุกจังหวัด (ทั้งหมด ${plotsCatalog.length} แปลง)</option>`;
  [...new Set(plotsCatalog.map(plot => plot.province))].sort().forEach(province => {
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
    filtered = filtered.filter(plot => plot.name.toLowerCase().includes(query) || plot.code.toLowerCase().includes(query) || plot.province.toLowerCase().includes(query));
  }
  renderSidebarList(filtered);
}

function renderSidebarList(plots) {
  const container = document.getElementById('plot-list-container');
  document.getElementById('sidebar-count-display').textContent = `แสดง ${plots.length} จาก ${allPlotsData.length} แปลง`;
  container.innerHTML = '';

  plots.forEach(plot => {
    const card = document.createElement('div');
    card.className = `plot-card-item ${activePlot?.id === plot.id ? 'active' : ''}`;
    card.id = `sidebar-card-${plot.id}`;
    card.dataset.plotId = String(plot.id);
    card.setAttribute('role','button');
    card.tabIndex = 0;

    const selectThisPlot = () => selectPlot(plot.id);
    card.addEventListener('click', selectThisPlot);
    card.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectThisPlot();
      }
    });

    card.innerHTML = `
      <div class="p-card-header">
        <span class="p-card-title" title="${escapeHtml(plot.name)}">${escapeHtml(plot.name)}</span>
        <span class="p-prov-tag">${escapeHtml(plot.province)}</span>
      </div>
      <div class="p-card-body">
        <span>เนื้อที่: <strong>${Number(plot.area_rai).toFixed(1)} ไร่</strong></span>
        <span>${isFiniteNumber(plot.gain_ndvi) ? `NDVI: <strong class="ndvi-gain">${plot.gain_ndvi >= 0 ? '+' : ''}${plot.gain_ndvi.toFixed(3)}</strong>` : '<strong>12 dates • รอ verified stats</strong>'}</span>
      </div>`;
    container.appendChild(card);
  });
}

function imageBoundsForPlot(plot) {
  const b = plot.bounds;
  return [[b[1] - IMAGE_BUFFER_DEG, b[0] - IMAGE_BUFFER_DEG],[b[3] + IMAGE_BUFFER_DEG, b[2] + IMAGE_BUFFER_DEG]];
}

function initPlotSatelliteMap() {
  plotSatelliteMap = L.map('plot-satellite-map', { zoomControl:true, attributionControl:true }).setView([12.75,101.80],15);
  L.tileLayer(ESRI_WORLD_IMAGERY,{ maxZoom:19, attribution:'Tiles &copy; Esri' }).addTo(plotSatelliteMap);
}

function updatePlotSatelliteViewer(plot) {
  if (!plotSatelliteMap || !plot.geometry) return;
  if (plotBoundaryLayer) plotSatelliteMap.removeLayer(plotBoundaryLayer);
  plotBoundaryLayer = L.geoJSON({ type:'Feature', properties:{id:plot.id,name:plot.name}, geometry:plot.geometry },{
    style:{color:'#34d399',weight:2,opacity:1,fillOpacity:0}
  }).addTo(plotSatelliteMap);
  const bounds = plotBoundaryLayer.getBounds();
  if (bounds.isValid()) plotSatelliteMap.fitBounds(bounds,{padding:[45,45],maxZoom:17,animate:false});
  togglePlotBoundary(document.getElementById('toggle-boundary-check')?.checked !== false);
}

function preloadImage(url) {
  return new Promise((resolve,reject) => {
    const image = new Image();
    image.onload = () => resolve();
    image.onerror = reject;
    image.src = url;
  });
}

function setPlotMapLayer(layerKey) {
  currentPlotLayerKey = layerKey;
  document.querySelectorAll('.band-btn-group .band-btn').forEach(button => button.classList.toggle('active',button.dataset.layer === layerKey));
  sentinelSwapToken++;
  if (layerKey === 'esri') {
    if (pendingSentinelOverlay && plotSatelliteMap?.hasLayer(pendingSentinelOverlay)) plotSatelliteMap.removeLayer(pendingSentinelOverlay);
    pendingSentinelOverlay = null;
    if (currentSentinelOverlay && plotSatelliteMap?.hasLayer(currentSentinelOverlay)) plotSatelliteMap.removeLayer(currentSentinelOverlay);
    currentSentinelOverlay = null;
    return;
  }
  updateGeeOverlay();
}

async function updateGeeOverlay() {
  if (!activePlot || !plotSatelliteMap || currentPlotLayerKey === 'esri') return;
  const item = activePlot.timeseries[currentMonthIndex];
  if (!item || !MILESTONE_MONTHS.includes(item.month)) return;
  const prefix = currentPlotLayerKey === 'gee_ndvi' ? 'ndvi' : 'rgb';
  const url = `data/plots/${activePlot.id}/${prefix}_${item.month}.png?v=${ASSET_VERSION}`;
  const token = ++sentinelSwapToken;

  try { await preloadImage(url); }
  catch (error) {
    if (token !== sentinelSwapToken) return;
    const label = document.getElementById('hud-month-label');
    if (label) label.textContent = `${fullThaiMonths[item.month_num]} ${item.year} • ไม่มีภาพ`;
    return;
  }

  if (token !== sentinelSwapToken || currentPlotLayerKey === 'esri') return;
  const oldOverlay = currentSentinelOverlay;
  const nextOverlay = L.imageOverlay(url,imageBoundsForPlot(activePlot),{ opacity:0, interactive:false, className:'sentinel-overlay' });
  pendingSentinelOverlay = nextOverlay;

  nextOverlay.once('load',() => {
    if (token !== sentinelSwapToken) {
      if (plotSatelliteMap.hasLayer(nextOverlay)) plotSatelliteMap.removeLayer(nextOverlay);
      return;
    }
    requestAnimationFrame(() => nextOverlay.setOpacity(1));
    setTimeout(() => {
      if (token !== sentinelSwapToken) return;
      if (oldOverlay && oldOverlay !== nextOverlay && plotSatelliteMap.hasLayer(oldOverlay)) plotSatelliteMap.removeLayer(oldOverlay);
      currentSentinelOverlay = nextOverlay;
      pendingSentinelOverlay = null;
      if (plotBoundaryLayer) plotBoundaryLayer.bringToFront();
    },300);
  });

  nextOverlay.once('error',() => {
    if (plotSatelliteMap.hasLayer(nextOverlay)) plotSatelliteMap.removeLayer(nextOverlay);
    if (pendingSentinelOverlay === nextOverlay) pendingSentinelOverlay = null;
  });

  nextOverlay.addTo(plotSatelliteMap);
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
  if (!status) { status = document.createElement('div'); status.className = 'integrity-chart-status'; container.appendChild(status); }
  status.classList.toggle('hidden',hasAnyMetric);
  status.textContent = 'ยังไม่มี verified 12-date statistics — ภาพดาวเทียมดูได้ แต่ไม่ใช้ค่า interpolated/synthetic เดิม';

  plotNdviChart = new Chart(document.getElementById('plotNdviChart').getContext('2d'),{
    type:'line',
    data:{
      labels:series.map(item => `${thaiMonths[item.month_num]} ${String(item.year).slice(2)}`),
      datasets:[
        { label:'Mean NDVI (observed/composite)', data:ndviData, borderColor:'#10b981', backgroundColor:'rgba(16,185,129,.10)', borderWidth:2.5, pointRadius:4, tension:0, spanGaps:false, yAxisID:'y' },
        { label:'Vegetation coverage proxy (NDVI > 0.25)', data:proxyData, borderColor:'#38bdf8', backgroundColor:'transparent', borderWidth:2, pointRadius:3, tension:0, spanGaps:false, yAxisID:'y1' }
      ]
    },
    options:{ responsive:true, maintainAspectRatio:false, interaction:{mode:'index',intersect:false}, onClick:(event,elements) => { if (elements?.length) setMonthIndex(elements[0].index); }, scales:{ x:{ticks:{color:'#64748b'},grid:{color:'rgba(255,255,255,.05)'}}, y:{min:-.1,max:.9,position:'left',ticks:{color:'#94a3b8'}}, y1:{min:0,max:100,position:'right',ticks:{color:'#94a3b8',callback:v => `${v}%`},grid:{drawOnChartArea:false}} } }
  });
}

function selectPlot(plotId) {
  const plot = allPlotsData.find(item => item.id === Number(plotId));
  if (!plot) return;

  sentinelSwapToken++;
  if (pendingSentinelOverlay && plotSatelliteMap?.hasLayer(pendingSentinelOverlay)) plotSatelliteMap.removeLayer(pendingSentinelOverlay);
  pendingSentinelOverlay = null;
  if (currentSentinelOverlay && plotSatelliteMap?.hasLayer(currentSentinelOverlay)) plotSatelliteMap.removeLayer(currentSentinelOverlay);
  currentSentinelOverlay = null;

  activePlot = plot;
  currentMonthIndex = Math.min(currentMonthIndex,MILESTONE_MONTHS.length - 1);

  document.querySelectorAll('.plot-card-item').forEach(card => card.classList.remove('active'));
  const activeCard = document.getElementById(`sidebar-card-${plot.id}`);
  if (activeCard) { activeCard.classList.add('active'); activeCard.scrollIntoView({behavior:'smooth',block:'nearest'}); }

  document.getElementById('kpi-current-plot-name').textContent = plot.name;
  document.getElementById('kpi-current-plot-sub').textContent = `เนื้อที่ ${Number(plot.area_rai).toFixed(1)} ไร่ • ${plot.centroid[0].toFixed(4)}°N, ${plot.centroid[1].toFixed(4)}°E (${plot.province})`;

  const gainEl = document.getElementById('kpi-plot-ndvi-gain');
  const gainSub = document.getElementById('kpi-plot-gain-pct');
  if (isFiniteNumber(plot.gain_ndvi)) {
    gainEl.textContent = `${plot.gain_ndvi >= 0 ? '+' : ''}${plot.gain_ndvi.toFixed(3)}`;
    gainSub.textContent = isFiniteNumber(plot.growth_pct) ? `${plot.growth_pct >= 0 ? '+' : ''}${plot.growth_pct.toFixed(1)}% จาก observed endpoints` : 'คำนวณจาก observed endpoints';
  } else { gainEl.textContent = '—'; gainSub.textContent = 'ยังไม่มี verified statistic'; }

  document.getElementById('kpi-plot-canopy-pct').textContent = isFiniteNumber(plot.current_vegetation_proxy_pct) ? `${plot.current_vegetation_proxy_pct.toFixed(1)}%` : '—';
  document.getElementById('chart-plot-title').textContent = `NDVI และ Vegetation Proxy — ${plot.name}`;

  renderPlotChart(plot);
  updatePlotSatelliteViewer(plot);
  initCompareSelectors(plot);
  comparePlotId = null;
  setMonthIndex(currentMonthIndex);

  if (document.getElementById('panel-compare')?.classList.contains('active')) setTimeout(updateCompareView,0);

  if (leafletMap && thailandGeojsonLayer) {
    thailandGeojsonLayer.eachLayer(layer => {
      const selected = layer.feature?.properties?.id === plot.id;
      layer.setStyle({ color:selected ? '#38bdf8' : '#10b981', weight:selected ? 4 : 2, fillOpacity:selected ? .12 : .04 });
      if (selected) layer.bringToFront();
    });
  }
}

function setMonthIndex(index) {
  if (!activePlot) return;
  const idx = Math.max(0,Math.min(11,Number(index) || 0));
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
  if (plotNdviChart) { plotNdviChart.setActiveElements([{datasetIndex:0,index:idx}]); plotNdviChart.update('none'); }
}

function onMonthSliderChange(value) { setMonthIndex(parseInt(value,10)); }
function prevMonth() { setMonthIndex((currentMonthIndex - 1 + 12) % 12); }
function nextMonth() { setMonthIndex((currentMonthIndex + 1) % 12); }
function togglePlay() { isPlaying ? pause() : play(); }
function play() { isPlaying = true; document.getElementById('play-icon').classList.add('hidden'); document.getElementById('pause-icon').classList.remove('hidden'); playInterval = setInterval(nextMonth,playbackSpeed); }
function pause() { isPlaying = false; document.getElementById('play-icon').classList.remove('hidden'); document.getElementById('pause-icon').classList.add('hidden'); if (playInterval) clearInterval(playInterval); playInterval = null; }

function initLeafletThailandMap() {
  leafletMap = L.map('thailand-map').setView([10.5,100.5],6);
  L.tileLayer(ESRI_WORLD_IMAGERY,{maxZoom:19,attribution:'Tiles &copy; Esri'}).addTo(leafletMap);
  fetch(`data/plots.geojson?v=${ASSET_VERSION}`,{cache:'no-store'}).then(response => response.json()).then(geojson => {
    thailandGeojsonLayer = L.geoJSON(geojson,{
      style:{color:'#10b981',weight:2,opacity:.95,fillColor:'#10b981',fillOpacity:.04},
      onEachFeature:(feature,layer) => {
        const p = feature.properties;
        layer.bindPopup(`<div class="popup-title">${escapeHtml(p.name)}</div><div class="popup-meta">จังหวัด: <strong>${escapeHtml(p.province)}</strong> | เนื้อที่: <strong>${Number(p.area_rai).toFixed(1)} ไร่</strong></div><button class="popup-btn" onclick="selectPlot(${p.id}); switchWorkspaceTab('detail');">ดูแปลงนี้</button>`);
        layer.on('click',() => selectPlot(p.id));
      }
    }).addTo(leafletMap);
  });
}

function resetMapZoom() { if (leafletMap) leafletMap.setView([10.5,100.5],6); }

function switchWorkspaceTab(tab) {
  document.querySelectorAll('.w-tab-btn').forEach(button => button.classList.remove('active'));
  document.querySelectorAll('.tab-content-panel').forEach(panel => panel.classList.remove('active'));
  document.getElementById(`wtab-${tab}`).classList.add('active');
  document.getElementById(`panel-${tab}`).classList.add('active');
  if (tab === 'detail' && plotSatelliteMap) setTimeout(() => { plotSatelliteMap.invalidateSize(); if (activePlot) updatePlotSatelliteViewer(activePlot); },100);
  if (tab === 'map' && leafletMap) setTimeout(() => leafletMap.invalidateSize(),100);
  if (tab === 'compare') setTimeout(() => { ensureCompareMaps(); updateCompareView(); compareLeftMap?.invalidateSize(); compareRightMap?.invalidateSize(); },100);
}

function initCompareSelectors(plot) {
  const left = document.getElementById('comp-left-select');
  const right = document.getElementById('comp-right-select');
  left.innerHTML = '';
  right.innerHTML = '';
  MILESTONE_MONTHS.forEach((monthKey,index) => {
    const item = plot.timeseries[index];
    const metric = isFiniteNumber(item.mean_ndvi_inside) ? ` • NDVI ${item.mean_ndvi_inside.toFixed(2)}` : '';
    const label = `${thaiMonths[item.month_num]} ${item.year}${metric}`;
    const l = document.createElement('option'); l.value = String(index); l.textContent = label; left.appendChild(l); right.appendChild(l.cloneNode(true));
  });
  left.value = '0';
  right.value = '11';
}

function ensureCompareMaps() {
  if (compareLeftMap && compareRightMap) return;
  const container = document.getElementById('compare-container');
  container.innerHTML = `
    <div class="compare-map-panel"><div id="compare-map-left" class="compare-leaflet-half"></div><div class="compare-side-label" id="comp-label-before">Before</div></div>
    <div class="compare-map-panel"><div id="compare-map-right" class="compare-leaflet-half"></div><div class="compare-side-label" id="comp-label-after">After</div></div>
    <div class="compare-center-divider"></div>`;

  compareLeftMap = L.map('compare-map-left',{ zoomControl:true, attributionControl:false, dragging:false, scrollWheelZoom:false, doubleClickZoom:false, boxZoom:false, keyboard:false }).setView([12.75,101.80],15);
  compareRightMap = L.map('compare-map-right',{ zoomControl:true, attributionControl:true, dragging:false, scrollWheelZoom:false, doubleClickZoom:false, boxZoom:false, keyboard:false }).setView([12.75,101.80],15);
  L.tileLayer(ESRI_WORLD_IMAGERY,{maxZoom:19}).addTo(compareLeftMap);
  L.tileLayer(ESRI_WORLD_IMAGERY,{maxZoom:19,attribution:'Tiles &copy; Esri'}).addTo(compareRightMap);
}

function replaceCompareLayer(map, existing, url, plot) {
  if (existing && map.hasLayer(existing)) map.removeLayer(existing);
  return L.imageOverlay(url,imageBoundsForPlot(plot),{ opacity:1, interactive:false, className:'sentinel-overlay' }).addTo(map);
}

function replaceCompareBoundary(map, existing, plot, show) {
  if (existing && map.hasLayer(existing)) map.removeLayer(existing);
  const layer = L.geoJSON({ type:'Feature', properties:{}, geometry:plot.geometry },{ style:{color:'#34d399',weight:2,opacity:1,fillOpacity:0} });
  if (show) layer.addTo(map);
  return layer;
}

function updateCompareView() {
  if (!activePlot) return;
  ensureCompareMaps();
  const leftIndex = Math.max(0,Math.min(11,parseInt(document.getElementById('comp-left-select').value || '0',10)));
  const rightIndex = Math.max(0,Math.min(11,parseInt(document.getElementById('comp-right-select').value || '11',10)));
  const mode = document.getElementById('comp-mode-select')?.value || 'rgb';
  const leftItem = activePlot.timeseries[leftIndex];
  const rightItem = activePlot.timeseries[rightIndex];

  let leftPrefix = 'rgb'; let rightPrefix = 'rgb';
  if (mode === 'ndvi') leftPrefix = rightPrefix = 'ndvi';
  if (mode === 'rgb_vs_ndvi') rightPrefix = 'ndvi';

  document.getElementById('comp-label-before').textContent = `${thaiMonths[leftItem.month_num]} ${leftItem.year} • ${leftPrefix.toUpperCase()}`;
  document.getElementById('comp-label-after').textContent = `${thaiMonths[rightItem.month_num]} ${rightItem.year} • ${rightPrefix.toUpperCase()}`;

  const leftUrl = `data/plots/${activePlot.id}/${leftPrefix}_${leftItem.month}.png?v=${ASSET_VERSION}`;
  const rightUrl = `data/plots/${activePlot.id}/${rightPrefix}_${rightItem.month}.png?v=${ASSET_VERSION}`;
  compareLeftOverlay = replaceCompareLayer(compareLeftMap,compareLeftOverlay,leftUrl,activePlot);
  compareRightOverlay = replaceCompareLayer(compareRightMap,compareRightOverlay,rightUrl,activePlot);

  const showBoundary = document.getElementById('comp-boundary-toggle')?.checked !== false;
  compareLeftBoundary = replaceCompareBoundary(compareLeftMap,compareLeftBoundary,activePlot,showBoundary);
  compareRightBoundary = replaceCompareBoundary(compareRightMap,compareRightBoundary,activePlot,showBoundary);
  comparePlotId = activePlot.id;

  const bounds = L.geoJSON({ type:'Feature', properties:{}, geometry:activePlot.geometry }).getBounds();
  if (bounds.isValid()) {
    const options = {padding:[34,34],maxZoom:17,animate:false};
    compareLeftMap.fitBounds(bounds,options);
    compareRightMap.fitBounds(bounds,options);
  }

  const leftNdvi = leftItem.mean_ndvi_inside;
  const rightNdvi = rightItem.mean_ndvi_inside;
  const statText = document.getElementById('comp-in-stat-text');
  const gainPill = document.getElementById('comp-gain-pill');
  if (isFiniteNumber(leftNdvi) && isFiniteNumber(rightNdvi)) {
    const diff = rightNdvi - leftNdvi;
    statText.innerHTML = `Mean NDVI: <strong>${leftNdvi.toFixed(3)}</strong> ➔ <strong>${rightNdvi.toFixed(3)}</strong>`;
    gainPill.textContent = `${diff >= 0 ? '+' : ''}${diff.toFixed(3)}`;
  } else {
    statText.textContent = 'Verified NDVI statistics ยังไม่ถูกสร้าง — แต่ภาพ Before/After ใช้งานได้';
    gainPill.textContent = 'No verified metric';
  }
}

function toggleCompareBoundary(show) {
  if (!activePlot || !compareLeftMap || !compareRightMap) return;
  if (compareLeftBoundary) { if (show && !compareLeftMap.hasLayer(compareLeftBoundary)) compareLeftBoundary.addTo(compareLeftMap); if (!show && compareLeftMap.hasLayer(compareLeftBoundary)) compareLeftMap.removeLayer(compareLeftBoundary); }
  if (compareRightBoundary) { if (show && !compareRightMap.hasLayer(compareRightBoundary)) compareRightBoundary.addTo(compareRightMap); if (!show && compareRightMap.hasLayer(compareRightBoundary)) compareRightMap.removeLayer(compareRightBoundary); }
}

function initTable(plots) {
  const tbody = document.getElementById('table-body');
  document.getElementById('table-count-label').textContent = `แสดงทั้งหมด ${plots.length} แปลง`;
  tbody.innerHTML = '';
  plots.forEach(plot => {
    const row = document.createElement('tr');
    row.innerHTML = `<td><strong>${escapeHtml(plot.code)}</strong></td><td>${escapeHtml(plot.name)}</td><td><span class="p-prov-tag">${escapeHtml(plot.province)}</span></td><td>${Number(plot.area_rai).toFixed(1)}</td><td>${isFiniteNumber(plot.initial_ndvi) ? plot.initial_ndvi.toFixed(3) : '—'}</td><td>${isFiniteNumber(plot.current_ndvi) ? plot.current_ndvi.toFixed(3) : '—'}</td><td><strong>${isFiniteNumber(plot.gain_ndvi) ? `${plot.gain_ndvi >= 0 ? '+' : ''}${plot.gain_ndvi.toFixed(3)}` : '—'}</strong></td><td>${isFiniteNumber(plot.current_vegetation_proxy_pct) ? plot.current_vegetation_proxy_pct.toFixed(1) : '—'}</td><td><button class="btn-table-view" data-plot-id="${plot.id}">ดูรายละเอียด</button></td>`;
    row.querySelector('.btn-table-view').addEventListener('click',() => { selectPlot(plot.id); switchWorkspaceTab('detail'); });
    tbody.appendChild(row);
  });
}

function exportPlotsCSV() {
  if (!allPlotsData.length) return;
  const headers = ['Plot ID','Plot Code','Plot Name','Province','Area (Rai)','Initial NDVI (Sep 2023)','Current NDVI (Aug 2026)','NDVI Gain','Vegetation Coverage Proxy %','Centroid Lat','Centroid Lon'];
  const clean = value => isFiniteNumber(value) ? value : '';
  const rows = allPlotsData.map(plot => [plot.id,`"${String(plot.code).replaceAll('"','""')}"`,`"${String(plot.name).replaceAll('"','""')}"`,`"${String(plot.province).replaceAll('"','""')}"`,Number(plot.area_rai).toFixed(2),clean(plot.initial_ndvi),clean(plot.current_ndvi),clean(plot.gain_ndvi),clean(plot.current_vegetation_proxy_pct),plot.centroid[0],plot.centroid[1]]);
  const csv = '\uFEFF' + [headers.join(','),...rows.map(row => row.join(','))].join('\n');
  const blob = new Blob([csv],{type:'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `mangrove_12_dates_${new Date().toISOString().slice(0,10)}.csv`; anchor.click(); URL.revokeObjectURL(url);
}

async function init() {
  try {
    injectRuntimeStyles();
    await loadData();
    updateStaticCopy();
    initProvinceFilter();
    renderSidebarList(allPlotsData);
    initPlotSatelliteMap();
    initLeafletThailandMap();
    initTable(allPlotsData);
    const defaultPlot = allPlotsData.find(plot => plot.province === 'ระยอง') || allPlotsData[0];
    if (defaultPlot) selectPlot(defaultPlot.id);
  } catch (error) {
    console.error('Initialization error:',error);
    const workspace = document.querySelector('.workspace-area');
    if (workspace) workspace.insertAdjacentHTML('afterbegin',`<div class="chart-box">โหลดข้อมูลไม่สำเร็จ: ${escapeHtml(error.message)}</div>`);
  }
}

document.addEventListener('DOMContentLoaded',init);
