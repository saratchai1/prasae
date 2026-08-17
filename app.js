// Prasae Mangrove Time-Series Interactive Dashboard Logic

let timeseriesData = [];
let currentIndex = 0;
let currentBandMode = 'rgb'; // 'rgb' | 'false_color' | 'ndvi'
let isPlaying = false;
let playInterval = null;
let playbackSpeed = 500; // ms per frame
let ndviChart = null;

// DOM Elements
const mainImg = document.getElementById('main-display-img');
const hudMonthTitle = document.getElementById('hud-month-title');
const hudBandType = document.getElementById('hud-band-type');
const hudScenesCount = document.getElementById('hud-scenes-count');
const hudMeanNdvi = document.getElementById('hud-mean-ndvi');
const hudCanopyCover = document.getElementById('hud-canopy-cover');
const ndviLegend = document.getElementById('ndvi-legend-overlay');
const timelineSlider = document.getElementById('timeline-slider');
const controlDateDisplay = document.getElementById('control-date-display');
const btnPlay = document.getElementById('btn-play');
const playIcon = document.getElementById('play-icon');
const pauseIcon = document.getElementById('pause-icon');

// Metric Elements
const valInitialNdvi = document.getElementById('val-initial-ndvi');
const valCurrentNdvi = document.getElementById('val-current-ndvi');
const valNdviGain = document.getElementById('val-ndvi-gain');
const valNdviGainPct = document.getElementById('val-ndvi-gain-pct');
const valCanopyPct = document.getElementById('val-canopy-pct');

// Compare Elements
const compareLeftSelect = document.getElementById('compare-left-select');
const compareRightSelect = document.getElementById('compare-right-select');
const compareImgBefore = document.getElementById('compare-img-before');
const compareImgAfter = document.getElementById('compare-img-after');
const compareBeforeWrapper = document.getElementById('compare-before-wrapper');
const compareDivider = document.getElementById('compare-divider');
const compareContainer = document.getElementById('compare-container');
const compareLabelBefore = document.getElementById('compare-label-before');
const compareLabelAfter = document.getElementById('compare-label-after');

// Thai Month Names
const thaiMonths = {
  1: 'มกราคม', 2: 'กุมภาพันธ์', 3: 'มีนาคม', 4: 'เมษายน',
  5: 'พฤษภาคม', 6: 'มิถุนายน', 7: 'กรกฎาคม', 8: 'สิงหาคม',
  9: 'กันยายน', 10: 'ตุลาคม', 11: 'พฤศจิกายน', 12: 'ธันวาคม'
};

const bandModeLabels = {
  rgb: 'Sentinel-2 L2A True Color (RGB)',
  false_color: 'Sentinel-2 Color Infrared (CIR / False Color)',
  ndvi: 'Sentinel-2 Normalized Difference Vegetation Index (NDVI)'
};

// Initialize Application
async function init() {
  try {
    const res = await fetch('data/timeseries.json');
    if (!res.ok) throw new Error('Cannot load data/timeseries.json');
    timeseriesData = await res.json();
    
    if (!timeseriesData || timeseriesData.length === 0) {
      console.warn('Timeseries data is empty');
      return;
    }

    timelineSlider.max = timeseriesData.length - 1;
    
    populateTicks();
    updateSummaryMetrics();
    initCompareSelectors();
    initCompareSlider();
    initGallery();
    initChart();
    
    // Set to final month or first month
    setMonthIndex(timeseriesData.length - 1);
  } catch (err) {
    console.error('Initialization error:', err);
  }
}

// Summary Metrics
function updateSummaryMetrics() {
  if (timeseriesData.length === 0) return;
  const initial = timeseriesData[0];
  const current = timeseriesData[timeseriesData.length - 1];

  valInitialNdvi.textContent = initial.mean_ndvi_plot.toFixed(3);
  valCurrentNdvi.textContent = current.mean_ndvi_plot.toFixed(3);

  const gain = current.mean_ndvi_plot - initial.mean_ndvi_plot;
  const gainPct = initial.mean_ndvi_plot > 0 ? (gain / initial.mean_ndvi_plot) * 100 : 0;

  valNdviGain.textContent = `${gain >= 0 ? '+' : ''}${gain.toFixed(3)}`;
  valNdviGainPct.textContent = `เพิ่มขึ้น ${gainPct.toFixed(0)}% จากจุดเริ่มต้นก่อนปลูก`;
  valCanopyPct.textContent = `${current.veg_coverage_pct.toFixed(1)}%`;
}

// Populate Timeline Ticks
function populateTicks() {
  const ticksContainer = document.getElementById('timeline-ticks');
  ticksContainer.innerHTML = '';
  
  const years = [2023, 2024, 2025, 2026];
  years.forEach(yr => {
    const span = document.createElement('span');
    span.textContent = yr;
    ticksContainer.appendChild(span);
  });
}

// Update View for Current Month Index
function setMonthIndex(idx) {
  if (idx < 0 || idx >= timeseriesData.length) return;
  currentIndex = idx;
  const item = timeseriesData[idx];

  timelineSlider.value = idx;
  
  const thMonth = thaiMonths[item.month_num];
  const label = `${thMonth} ${item.year}`;
  
  hudMonthTitle.textContent = label;
  controlDateDisplay.textContent = `${item.month_name.slice(0, 3)} ${item.year}`;
  hudBandType.textContent = bandModeLabels[currentBandMode];
  hudScenesCount.textContent = `${item.scenes_used} scenes composited`;
  hudMeanNdvi.textContent = item.mean_ndvi_plot.toFixed(3);
  hudCanopyCover.textContent = `${item.veg_coverage_pct.toFixed(1)}%`;

  // Update Image Source
  let imgPath = item.rgb_file;
  if (currentBandMode === 'false_color') imgPath = item.fc_file;
  if (currentBandMode === 'ndvi') imgPath = item.ndvi_file;

  mainImg.src = imgPath;

  if (currentBandMode === 'ndvi') {
    ndviLegend.classList.add('visible');
  } else {
    ndviLegend.classList.remove('visible');
  }

  // Highlight active point in Chart
  if (ndviChart) {
    ndviChart.setActiveElements([
      { datasetIndex: 0, index: idx },
      { datasetIndex: 1, index: idx }
    ]);
    ndviChart.update('none');
  }
}

function onSliderChange(val) {
  setMonthIndex(parseInt(val, 10));
}

function prevMonth() {
  if (currentIndex > 0) {
    setMonthIndex(currentIndex - 1);
  } else {
    setMonthIndex(timeseriesData.length - 1);
  }
}

function nextMonth() {
  if (currentIndex < timeseriesData.length - 1) {
    setMonthIndex(currentIndex + 1);
  } else {
    setMonthIndex(0);
  }
}

function togglePlay() {
  if (isPlaying) {
    pause();
  } else {
    play();
  }
}

function play() {
  isPlaying = true;
  playIcon.classList.add('hidden');
  pauseIcon.classList.remove('hidden');
  
  playInterval = setInterval(() => {
    nextMonth();
  }, playbackSpeed);
}

function pause() {
  isPlaying = false;
  playIcon.classList.remove('hidden');
  pauseIcon.classList.add('hidden');
  if (playInterval) clearInterval(playInterval);
}

function setSpeed(val) {
  playbackSpeed = parseInt(val, 10);
  if (isPlaying) {
    pause();
    play();
  }
}

// Band Switcher
function setBandMode(mode) {
  currentBandMode = mode;
  document.querySelectorAll('.band-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.band === mode);
  });
  setMonthIndex(currentIndex);
  updateCompareImages();
}

// Tab Switcher
function switchViewerTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.view-panel').forEach(p => p.classList.remove('active'));

  if (tabName === 'single') {
    document.getElementById('tab-single').classList.add('active');
    document.getElementById('panel-single').classList.add('active');
  } else if (tabName === 'compare') {
    document.getElementById('tab-compare').classList.add('active');
    document.getElementById('panel-compare').classList.add('active');
    updateCompareImages();
  } else if (tabName === 'gallery') {
    document.getElementById('tab-gallery').classList.add('active');
    document.getElementById('panel-gallery').classList.add('active');
  }
}

// Compare Mode Logic
function initCompareSelectors() {
  compareLeftSelect.innerHTML = '';
  compareRightSelect.innerHTML = '';

  timeseriesData.forEach((d, i) => {
    const optLeft = document.createElement('option');
    optLeft.value = i;
    optLeft.textContent = `${d.month_name.slice(0, 3)} ${d.year} (NDVI: ${d.mean_ndvi_plot.toFixed(2)})`;
    compareLeftSelect.appendChild(optLeft);

    const optRight = document.createElement('option');
    optRight.value = i;
    optRight.textContent = `${d.month_name.slice(0, 3)} ${d.year} (NDVI: ${d.mean_ndvi_plot.toFixed(2)})`;
    compareRightSelect.appendChild(optRight);
  });

  // Default: Left = Sep 2023 (0), Right = Aug 2026 (last)
  compareLeftSelect.value = 0;
  compareRightSelect.value = timeseriesData.length - 1;
}

function updateCompareImages() {
  if (timeseriesData.length === 0) return;
  const leftIdx = parseInt(compareLeftSelect.value, 10);
  const rightIdx = parseInt(compareRightSelect.value, 10);

  const leftItem = timeseriesData[leftIdx];
  const rightItem = timeseriesData[rightIdx];

  let leftFile = leftItem.rgb_file;
  let rightFile = rightItem.rgb_file;

  if (currentBandMode === 'false_color') {
    leftFile = leftItem.fc_file;
    rightFile = rightItem.fc_file;
  } else if (currentBandMode === 'ndvi') {
    leftFile = leftItem.ndvi_file;
    rightFile = rightItem.ndvi_file;
  }

  compareImgBefore.src = leftFile;
  compareImgAfter.src = rightFile;

  compareLabelBefore.textContent = `Before: ${leftItem.month_name.slice(0, 3)} ${leftItem.year}`;
  compareLabelAfter.textContent = `After: ${rightItem.month_name.slice(0, 3)} ${rightItem.year}`;
}

function initCompareSlider() {
  let isDragging = false;

  const onMove = (e) => {
    if (!isDragging) return;
    const rect = compareContainer.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    let x = clientX - rect.left;
    x = Math.max(0, Math.min(x, rect.width));
    const pct = (x / rect.width) * 100;
    
    compareBeforeWrapper.style.width = `${pct}%`;
    compareDivider.style.left = `${pct}%`;
  };

  const startDrag = (e) => {
    isDragging = true;
    onMove(e);
  };

  const stopDrag = () => {
    isDragging = false;
  };

  compareContainer.addEventListener('mousedown', startDrag);
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', stopDrag);

  compareContainer.addEventListener('touchstart', startDrag);
  window.addEventListener('touchmove', onMove);
  window.addEventListener('touchend', stopDrag);
}

// Gallery Population
function initGallery() {
  const container = document.getElementById('gallery-grid-container');
  container.innerHTML = '';

  timeseriesData.forEach((d, i) => {
    const card = document.createElement('div');
    card.className = 'gallery-card';
    card.onclick = () => {
      setMonthIndex(i);
      switchViewerTab('single');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    card.innerHTML = `
      <div class="gallery-thumb-wrapper">
        <img src="${d.rgb_file}" alt="${d.month}" loading="lazy">
      </div>
      <div class="gallery-card-body">
        <div class="gallery-month-title">${d.month_name.slice(0, 3)} ${d.year}</div>
        <div class="gallery-stat-row">
          <span>NDVI: <strong class="ndvi-val">${d.mean_ndvi_plot.toFixed(2)}</strong></span>
          <span>Cover: <strong>${d.veg_coverage_pct.toFixed(0)}%</strong></span>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

// Time-Series Chart
function initChart() {
  const ctx = document.getElementById('ndviChart').getContext('2d');

  const labels = timeseriesData.map(d => `${d.month_name.slice(0, 3)} ${d.year.toString().slice(2)}`);
  const ndviValues = timeseriesData.map(d => d.mean_ndvi_plot);
  const canopyValues = timeseriesData.map(d => d.veg_coverage_pct);

  ndviChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'ค่าเฉลี่ยดัชนีพืชพรรณ (Mean NDVI)',
          data: ndviValues,
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
          label: 'สัดส่วนพื้นที่ทรงพุ่ม (% Canopy Cover)',
          data: canopyValues,
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
          switchViewerTab('single');
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
                return `Mean NDVI: ${context.parsed.y.toFixed(3)}`;
              }
              return `Canopy Cover: ${context.parsed.y.toFixed(1)}%`;
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
          min: -0.1,
          max: 0.8,
          title: {
            display: true,
            text: 'Mean NDVI',
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

// Auto start when DOM loaded
document.addEventListener('DOMContentLoaded', init);
