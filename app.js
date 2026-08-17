// Nationwide Mangrove Monitoring Portal (160+ Plots In-Boundary NDVI & High-Res Satellite GIS)

let plotsCatalog = [];
let allPlotsData = [];
let activePlot = null;
let currentMonthIndex = 0;
let currentPlotLayerKey = 'esri';
let isPlaying = false;
let playInterval = null;
let playbackSpeed = 500;
let plotNdviChart = null;

// Maps
let leafletMap = null; // Thailand Overview Map
let thailandGeojsonLayer = null;
let plotSatelliteMap = null; // Dedicated Selected Plot Satellite Viewer
let plotBoundaryLayer = null;
let plotBaseLayers = {};
let currentGeeOverlay = null;

// Thai Month Names
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

// Initialize App
async function init() {
  try {
    const [catRes, timeRes] = await Promise.all([
      fetch('data/plots_catalog.json'),
      fetch('data/timeseries_all_plots.json')
    ]);
    
    plotsCatalog = await catRes.json();
    allPlotsData = await timeRes.json();

    initProvinceFilter();
    renderSidebarList(allPlotsData);
    initPlotSatelliteMap();
    initLeafletThailandMap();
    initTable(allPlotsData);

    // Default select Plot in Rayong / Prasae (e.g. แปลง 22) or first plot
    const defaultPlot = allPlotsData.find(p => p.province === 'ระยอง') || allPlotsData[0];
    selectPlot(defaultPlot.id);

  } catch (err) {
    console.error('Initialization error:', err);
  }
}

// 1. Plot Satellite Viewer (Leaflet Map dedicated to current plot)
function initPlotSatelliteMap() {
  plotSatelliteMap = L.map('plot-satellite-map', {
    zoomControl: true,
    attributionControl: false
  }).setView([12.75, 101.80], 15);

  // Satellite Base Layers
  plotBaseLayers['esri'] = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19
  });



  plotBaseLayers['esri'].addTo(plotSatelliteMap);
}

function setPlotMapLayer(layerKey) {
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
}

function togglePlotBoundary(show) {
  if (!plotSatelliteMap || !plotBoundaryLayer) return;
  if (show) {
    if (!plotSatelliteMap.hasLayer(plotBoundaryLayer)) {
      plotBoundaryLayer.addTo(plotSatelliteMap);
      plotBoundaryLayer.bringToFront();
    }
  } else {
    if (plotSatelliteMap.hasLayer(plotBoundaryLayer)) {
      plotSatelliteMap.removeLayer(plotBoundaryLayer);
    }
  }
}

// 2. Select and Zoom to a Specific Plot
function selectPlot(plotId) {
  const plot = allPlotsData.find(p => p.id === plotId);
  if (!plot) return;
  
  activePlot = plot;

  // Update Sidebar active state
  document.querySelectorAll('.plot-card-item').forEach(c => c.classList.remove('active'));
  const activeCard = document.getElementById(`sidebar-card-${plot.id}`);
  if (activeCard) {
    activeCard.classList.add('active');
    activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Update KPI Cards
  document.getElementById('kpi-current-plot-name').textContent = plot.name;
  document.getElementById('kpi-current-plot-sub').textContent = `เนื้อที่ ${plot.area_rai.toFixed(1)} ไร่ • พิกัด ${plot.centroid[0].toFixed(4)}°N, ${plot.centroid[1].toFixed(4)}°E (${plot.province})`;
  
  const gainSign = plot.gain_ndvi >= 0 ? '+' : '';
  document.getElementById('kpi-plot-ndvi-gain').textContent = `${gainSign}${plot.gain_ndvi.toFixed(3)}`;
  document.getElementById('kpi-plot-gain-pct').textContent = `เพิ่มขึ้น +${plot.growth_pct.toFixed(0)}% (เฉพาะพิกเซลในกรอบแปลง)`;
  document.getElementById('kpi-plot-canopy-pct').textContent = `${plot.current_canopy_pct.toFixed(1)}%`;

  // Update Chart Title
  document.getElementById('chart-plot-title').textContent = `กราฟวิเคราะห์การเติบโตค่า NDVI (เฉพาะในกรอบแปลง): ${plot.name}`;

  // Render / Update Chart
  renderPlotChart(plot);

  // Update Plot Satellite Viewer with Exact KMZ Boundary
  updatePlotSatelliteViewer(plot);

  // Load GEE image if active
  updateGeeOverlay();

  // Update HUD
  setMonthIndex(currentMonthIndex);

  // Update Compare Selectors
  initCompareSelectors(plot);

  // Highlight on Thailand Map
  if (leafletMap && thailandGeojsonLayer) {
    thailandGeojsonLayer.eachLayer(layer => {
      if (layer.feature.properties.id === plot.id) {
        layer.setStyle({ color: '#38bdf8', weight: 4, fillOpacity: 0.6 });
        layer.bringToFront();
      } else {
        layer.setStyle({ color: '#10b981', weight: 2, fillOpacity: 0.25 });
      }
    });
  }
}

// Update the Plot Satellite Map with exact KMZ Polygon Boundary
function updatePlotSatelliteViewer(plot) {
  if (!plotSatelliteMap || !plot.geometry) return;

  // Remove previous boundary layer
  if (plotBoundaryLayer) {
    plotSatelliteMap.removeLayer(plotBoundaryLayer);
  }

  // Create GeoJSON layer for this plot polygon
  const plotGeoJson = {
    type: "Feature",
    properties: { id: plot.id, name: plot.name },
    geometry: plot.geometry
  };

  plotBoundaryLayer = L.geoJSON(plotGeoJson, {
    style: {
      color: '#34d399',          // Neon emerald outline
      weight: 3.5,
      opacity: 1.0,
      dashArray: '6, 4',
      fillColor: '#10b981',      // Translucent green fill inside boundary
      fillOpacity: 0.25
    }
  }).addTo(plotSatelliteMap);

  // Fit bounds precisely around the plot with padding
  const bounds = plotBoundaryLayer.getBounds();
  if (bounds.isValid()) {
    plotSatelliteMap.fitBounds(bounds, {
      padding: [45, 45],
      maxZoom: 17,
      animate: true
    });
  }

  // Ensure layer is visible if checkbox is checked
  const isChecked = document.getElementById('toggle-boundary-check').checked;
  togglePlotBoundary(isChecked);
}

// 3. Render Plot In-Boundary NDVI Chart (Strictly In-Boundary)
function renderPlotChart(plot) {
  const ctx = document.getElementById('plotNdviChart').getContext('2d');
  
  const labels = plot.timeseries.map(d => `${thaiMonths[d.month_num]} ${d.year.toString().slice(2)}`);
  const ndviData = plot.timeseries.map(d => d.mean_ndvi_inside);
  const canopyData = plot.timeseries.map(d => d.canopy_coverage_pct);

  if (plotNdviChart) {
    plotNdviChart.destroy();
  }

  plotNdviChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'In-Boundary Mean NDVI (เฉพาะในกรอบแปลง)',
          data: ndviData,
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.15)',
          borderWidth: 3,
          fill: true,
          tension: 0.35,
          pointRadius: 4,
          pointHoverRadius: 7,
          pointBackgroundColor: '#10b981',
          pointBorderColor: '#ffffff',
          pointBorderWidth: 2,
          yAxisID: 'y'
        },
        {
          label: 'In-Boundary % ทรงพุ่ม (Canopy Cover)',
          data: canopyData,
          borderColor: '#38bdf8',
          backgroundColor: 'transparent',
          borderWidth: 2,
          borderDash: [4, 4],
          pointRadius: 3,
          pointHoverRadius: 6,
          pointBackgroundColor: '#38bdf8',
          yAxisID: 'y1'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false
      },
      onClick: (e, elements) => {
        if (elements && elements.length > 0) {
          const clickedIdx = elements[0].index;
          setMonthIndex(clickedIdx);
        }
      },
      plugins: {
        legend: {
          labels: {
            color: '#94a3b8',
            font: { family: 'Plus Jakarta Sans', size: 12, weight: 600 }
          }
        },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          padding: 10,
          callbacks: {
            label: function(context) {
              if (context.datasetIndex === 0) {
                return `Mean NDVI (ในกรอบแปลง): ${context.parsed.y.toFixed(3)}`;
              }
              return `Canopy Cover (ในกรอบแปลง): ${context.parsed.y.toFixed(1)}%`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { color: '#64748b', font: { family: 'Plus Jakarta Sans', size: 11 } }
        },
        y: {
          type: 'linear',
          display: true,
          position: 'left',
          min: -0.05,
          max: 0.75,
          title: {
            display: true,
            text: 'Mean NDVI (In-Boundary)',
            color: '#10b981',
            font: { family: 'Plus Jakarta Sans', size: 12, weight: 600 }
          },
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { color: '#94a3b8' }
        },
        y1: {
          type: 'linear',
          display: true,
          position: 'right',
          min: 0,
          max: 100,
          title: {
            display: true,
            text: '% Canopy Cover',
            color: '#38bdf8',
            font: { family: 'Plus Jakarta Sans', size: 12, weight: 600 }
          },
          grid: { drawOnChartArea: false },
          ticks: {
            color: '#94a3b8',
            callback: value => `${value}%`
          }
        }
      }
    }
  });
}

// 4. Timeline Scrubber & HUD Update
function setMonthIndex(idx) {
  if (!activePlot || idx < 0 || idx >= 36) return;
  currentMonthIndex = idx;
  const item = activePlot.timeseries[idx];

  document.getElementById('month-slider').value = idx;
  document.getElementById('playback-date-display').textContent = `${thaiMonths[item.month_num]} ${item.year}`;
  document.getElementById('hud-month-label').textContent = `${fullThaiMonths[item.month_num]} ${item.year}`;
  document.getElementById('hud-plot-label').textContent = `${activePlot.name} (${activePlot.province})`;
  document.getElementById('hud-coords-label').textContent = `${activePlot.centroid[0].toFixed(4)}°N, ${activePlot.centroid[1].toFixed(4)}°E • ${activePlot.area_rai.toFixed(1)} ไร่`;
  document.getElementById('hud-in-ndvi').textContent = item.mean_ndvi_inside.toFixed(3);
  document.getElementById('hud-in-cover').textContent = `${item.canopy_coverage_pct.toFixed(1)}%`;

  // Highlight active point in Chart
  if (plotNdviChart) {
    plotNdviChart.setActiveElements([
      { datasetIndex: 0, index: idx },
      { datasetIndex: 1, index: idx }
    ]);
    plotNdviChart.update('none');
  }
}

function onMonthSliderChange(val) {
  setMonthIndex(parseInt(val, 10));
}

function prevMonth() {
  if (currentMonthIndex > 0) setMonthIndex(currentMonthIndex - 1);
  else setMonthIndex(35);
}

function nextMonth() {
  if (currentMonthIndex < 35) setMonthIndex(currentMonthIndex + 1);
  else setMonthIndex(0);
}

function togglePlay() {
  if (isPlaying) pause();
  else play();
}

function play() {
  isPlaying = true;
  document.getElementById('play-icon').classList.add('hidden');
  document.getElementById('pause-icon').classList.remove('hidden');
  playInterval = setInterval(() => nextMonth(), playbackSpeed);
}

function pause() {
  isPlaying = false;
  document.getElementById('play-icon').classList.remove('hidden');
  document.getElementById('pause-icon').classList.add('hidden');
  if (playInterval) clearInterval(playInterval);
}

// 5. Province Filter Population
function initProvinceFilter() {
  const select = document.getElementById('province-filter');
  const provinces = [...new Set(plotsCatalog.map(p => p.province))].sort();
  
  provinces.forEach(prov => {
    const opt = document.createElement('option');
    opt.value = prov;
    const count = plotsCatalog.filter(p => p.province === prov).length;
    opt.textContent = `${prov} (${count} แปลง)`;
    select.appendChild(opt);
  });
}

function onProvinceFilterChange(prov) {
  const searchVal = document.getElementById('plot-search-input').value.toLowerCase().trim();
  filterPlots(prov, searchVal);
}

function onPlotSearchInput(searchVal) {
  const prov = document.getElementById('province-filter').value;
  filterPlots(prov, searchVal.toLowerCase().trim());
}

function filterPlots(prov, searchVal) {
  let filtered = allPlotsData;
  if (prov !== 'ALL') {
    filtered = filtered.filter(p => p.province === prov);
  }
  if (searchVal) {
    filtered = filtered.filter(p => 
      p.name.toLowerCase().includes(searchVal) ||
      p.code.toLowerCase().includes(searchVal) ||
      p.province.toLowerCase().includes(searchVal)
    );
  }
  renderSidebarList(filtered);
}

// Render Sidebar List
function renderSidebarList(plots) {
  const container = document.getElementById('plot-list-container');
  const countDisplay = document.getElementById('sidebar-count-display');
  container.innerHTML = '';
  
  countDisplay.textContent = `แสดง ${plots.length} จาก ${allPlotsData.length} แปลง`;

  plots.forEach(plot => {
    const card = document.createElement('div');
    card.className = `plot-card-item ${activePlot && activePlot.id === plot.id ? 'active' : ''}`;
    card.id = `sidebar-card-${plot.id}`;
    card.onclick = () => selectPlot(plot.id);

    const gainSign = plot.gain_ndvi >= 0 ? '+' : '';
    card.innerHTML = `
      <div class="p-card-header">
        <span class="p-card-title" title="${plot.name}">${plot.name}</span>
        <span class="p-prov-tag">${plot.province}</span>
      </div>
      <div class="p-card-body">
        <span>เนื้อที่: <strong>${plot.area_rai.toFixed(1)} ไร่</strong></span>
        <span>NDVI: <strong class="ndvi-gain">${gainSign}${plot.gain_ndvi.toFixed(2)}</strong> (+${plot.growth_pct.toFixed(0)}%)</span>
      </div>
    `;
    container.appendChild(card);
  });
}

// 6. Thailand Overview Leaflet Map
function initLeafletThailandMap() {
  leafletMap = L.map('thailand-map').setView([10.5, 100.5], 6);

  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
    maxZoom: 19
  }).addTo(leafletMap);

  fetch('data/plots.geojson')
    .then(r => r.json())
    .then(geojson => {
      thailandGeojsonLayer = L.geoJSON(geojson, {
        style: feature => ({
          color: '#10b981',
          weight: 2,
          opacity: 0.9,
          fillColor: '#10b981',
          fillOpacity: 0.25
        }),
        onEachFeature: (feature, layer) => {
          const p = feature.properties;
          const popupContent = `
            <div class="popup-title">${p.name}</div>
            <div class="popup-meta">จังหวัด: <strong>${p.province}</strong> | เนื้อที่: <strong>${p.area_rai.toFixed(1)} ไร่</strong></div>
            <button class="popup-btn" onclick="selectPlot(${p.id}); switchWorkspaceTab('detail');">วิเคราะห์แปลงนี้ (In-Boundary)</button>
          `;
          layer.bindPopup(popupContent);

          layer.on('click', () => {
            selectPlot(p.id);
          });
        }
      }).addTo(leafletMap);
    });
}

function resetMapZoom() {
  if (leafletMap) {
    leafletMap.setView([10.5, 100.5], 6);
  }
}

// 7. Workspace Tab Switcher
function switchWorkspaceTab(tab) {
  document.querySelectorAll('.w-tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content-panel').forEach(p => p.classList.remove('active'));

  document.getElementById(`wtab-${tab}`).classList.add('active');
  document.getElementById(`panel-${tab}`).classList.add('active');

  if (tab === 'detail' && plotSatelliteMap) {
    setTimeout(() => {
      plotSatelliteMap.invalidateSize();
      if (activePlot) updatePlotSatelliteViewer(activePlot);
    }, 200);
  }
  if (tab === 'map' && leafletMap) {
    setTimeout(() => leafletMap.invalidateSize(), 200);
  }
}

// 8. Compare View
function initCompareSelectors(plot) {
  const leftSel = document.getElementById('comp-left-select');
  const rightSel = document.getElementById('comp-right-select');
  leftSel.innerHTML = '';
  rightSel.innerHTML = '';

  plot.timeseries.forEach((d, i) => {
    const optL = document.createElement('option');
    optL.value = i;
    optL.textContent = `${thaiMonths[d.month_num]} ${d.year} (NDVI: ${d.mean_ndvi_inside.toFixed(2)})`;
    leftSel.appendChild(optL);

    const optR = document.createElement('option');
    optR.value = i;
    optR.textContent = `${thaiMonths[d.month_num]} ${d.year} (NDVI: ${d.mean_ndvi_inside.toFixed(2)})`;
    rightSel.appendChild(optR);
  });

  leftSel.value = 0; // Sep 2023
  rightSel.value = 35; // Aug 2026
  updateCompareView();
}

function updateCompareView() {
  if (!activePlot) return;
  
  const leftIdx = parseInt(document.getElementById('comp-left-select').value, 10);
  const rightIdx = parseInt(document.getElementById('comp-right-select').value, 10);
  
  const itemL = activePlot.timeseries[leftIdx];
  const itemR = activePlot.timeseries[rightIdx];
  
  if (!itemL || !itemR) return;
  
  document.getElementById('comp-label-before').textContent = `${thaiMonths[itemL.month_num]} ${itemL.year}`;
  document.getElementById('comp-label-after').textContent = `${thaiMonths[itemR.month_num]} ${itemR.year}`;
  
  const getClosest = (y, m) => {
    const targetVal = y * 12 + m;
    let closest = MILESTONE_MONTHS[0];
    let minDiff = 999;
    MILESTONE_MONTHS.forEach(ms => {
      const [yy, mm] = ms.split('-').map(Number);
      const val = yy * 12 + mm;
      if (Math.abs(val - targetVal) < minDiff) {
        minDiff = Math.abs(val - targetVal);
        closest = ms;
      }
    });
    return closest;
  };
  
  const msL = getClosest(itemL.year, itemL.month_num);
  const msR = getClosest(itemR.year, itemR.month_num);
  
  const imgL = `data/plots/${activePlot.id}/rgb_${msL}.png`;
  const imgR = `data/plots/${activePlot.id}/rgb_${msR}.png`;
  
  const beforeMap = document.getElementById('compare-before-map');
  const afterMap = document.getElementById('compare-after-map');
  
  beforeMap.style.backgroundImage = `url(${imgL})`;
  beforeMap.style.backgroundSize = '100% 100%';
  beforeMap.style.backgroundPosition = 'center';
  beforeMap.style.backgroundRepeat = 'no-repeat';

  afterMap.style.backgroundImage = `url(${imgR})`;
  afterMap.style.backgroundSize = '100% 100%';
  afterMap.style.backgroundPosition = 'center';
  afterMap.style.backgroundRepeat = 'no-repeat';
}

function initCompareSlider() {
  const container = document.getElementById('compare-container');
  const wrapper = document.getElementById('comp-before-wrapper');
  const divider = document.getElementById('comp-divider');
  let isDragging = false;

  if (!container || !wrapper || !divider) return;

  const slide = (e) => {
    if (!isDragging) return;
    const rect = container.getBoundingClientRect();
    // Support touch and mouse
    let clientX = e.clientX;
    if (e.touches && e.touches.length > 0) clientX = e.touches[0].clientX;
    
    let x = clientX - rect.left;
    x = Math.max(0, Math.min(x, rect.width));
    const pct = (x / rect.width) * 100;
    wrapper.style.width = pct + '%';
    divider.style.left = pct + '%';
  };

  divider.addEventListener('mousedown', () => isDragging = true);
  divider.addEventListener('touchstart', () => isDragging = true);
  
  window.addEventListener('mouseup', () => isDragging = false);
  window.addEventListener('touchend', () => isDragging = false);
  
  window.addEventListener('mousemove', slide);
  window.addEventListener('touchmove', slide);
}

document.addEventListener('DOMContentLoaded', initCompareSlider);


// 9. Table Tab
function initTable(plots) {
  const tbody = document.getElementById('table-body');
  document.getElementById('table-count-label').textContent = `แสดงทั้งหมด ${plots.length} แปลง`;
  tbody.innerHTML = '';

  plots.forEach(p => {
    const tr = document.createElement('tr');
    const gainSign = p.gain_ndvi >= 0 ? '+' : '';
    tr.innerHTML = `
      <td><strong>${p.code}</strong></td>
      <td>${p.name}</td>
      <td><span class="p-prov-tag">${p.province}</span></td>
      <td>${p.area_rai.toFixed(1)}</td>
      <td>${p.initial_ndvi.toFixed(3)}</td>
      <td>${p.current_ndvi.toFixed(3)}</td>
      <td class="text-success"><strong>${gainSign}${p.gain_ndvi.toFixed(3)}</strong> (+${p.growth_pct.toFixed(0)}%)</td>
      <td>${p.current_canopy_pct.toFixed(1)}%</td>
      <td><button class="btn-table-view" onclick="selectPlot(${p.id}); switchWorkspaceTab('detail');">ดูรายละเอียด</button></td>
    `;
    tbody.appendChild(tr);
  });
}

function exportPlotsCSV() {
  if (!allPlotsData || allPlotsData.length === 0) return;
  const headers = ['Plot ID', 'Plot Code', 'Plot Name', 'Province', 'Area (Rai)', 'Initial NDVI (Sep 2023)', 'Current NDVI (Aug 2026)', 'NDVI Gain', 'Growth %', 'Canopy Cover %', 'Centroid Lat', 'Centroid Lon'];
  const rows = allPlotsData.map(p => [
    p.id,
    `"${p.code}"`,
    `"${p.name}"`,
    `"${p.province}"`,
    p.area_rai.toFixed(2),
    p.initial_ndvi.toFixed(4),
    p.current_ndvi.toFixed(4),
    p.gain_ndvi.toFixed(4),
    p.growth_pct.toFixed(1),
    p.current_canopy_pct.toFixed(1),
    p.centroid[0],
    p.centroid[1]
  ]);

  const csvContent = '\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `mangrove_160_plots_summary_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
}

// Auto start
document.addEventListener('DOMContentLoaded', init);
