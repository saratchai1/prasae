// Enhanced mangrove metric presentation.
// Keeps core plot selection / compare logic untouched.

const METRIC_V2_VERSION = '20260817-2340';
const baseNormalizePlotV2 = normalizePlot;

normalizePlot = function(plot, catalogPlot) {
  const base = baseNormalizePlotV2(plot, catalogPlot);
  const sourceByMonth = new Map((plot.timeseries || []).map(item => [item.month, item]));

  base.timeseries = base.timeseries.map(item => {
    const sourceItem = sourceByMonth.get(item.month) || {};
    const numberOrNull = key => isFiniteNumber(sourceItem[key]) ? sourceItem[key] : null;
    return {
      ...item,
      proxy_version: sourceItem.proxy_version || plot.proxy_version || null,
      ndvi_p10_inside: numberOrNull('ndvi_p10_inside'),
      ndvi_p90_inside: numberOrNull('ndvi_p90_inside'),
      canopy_ndvi_median: numberOrNull('canopy_ndvi_median'),
      ndre_median: numberOrNull('ndre_median'),
      evi_median: numberOrNull('evi_median'),
      mfi_median: numberOrNull('mfi_median'),
      mfi_positive_pct: numberOrNull('mfi_positive_pct'),
      mndwi_median: numberOrNull('mndwi_median'),
      open_water_pct: numberOrNull('open_water_pct'),
      open_nonvegetated_pct: numberOrNull('open_nonvegetated_pct'),
      proxy_area_rai: numberOrNull('proxy_area_rai'),
      open_water_area_rai: numberOrNull('open_water_area_rai'),
      scene_metadata: Array.isArray(sourceItem.scene_metadata) ? sourceItem.scene_metadata : []
    };
  });

  base.proxy_version = plot.proxy_version || null;
  base.current_canopy_ndvi_median = isFiniteNumber(plot.current_canopy_ndvi_median)
    ? plot.current_canopy_ndvi_median : null;
  base.current_ndre_median = isFiniteNumber(plot.current_ndre_median)
    ? plot.current_ndre_median : null;
  base.current_open_water_pct = isFiniteNumber(plot.current_open_water_pct)
    ? plot.current_open_water_pct : null;
  return base;
};

function fmtMetric(value, digits = 3, suffix = '') {
  return isFiniteNumber(value) ? `${value.toFixed(digits)}${suffix}` : '—';
}

function ensureMangroveMetricPanel() {
  if (document.getElementById('mangrove-metric-v2-panel')) return;
  const chartBox = document.querySelector('#panel-detail .chart-box');
  if (!chartBox) return;

  const style = document.createElement('style');
  style.id = 'mangrove-metric-v2-style';
  style.textContent = `
    .mangrove-metric-v2-panel {
      display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.65rem;
      margin-top:1rem;
    }
    .mangrove-metric-v2-card {
      background:rgba(15,23,42,.64); border:1px solid rgba(255,255,255,.08);
      border-radius:10px; padding:.7rem .8rem; min-width:0;
    }
    .mangrove-metric-v2-label { font-size:.67rem; color:#94a3b8; font-weight:700; line-height:1.25; }
    .mangrove-metric-v2-value { font-size:1.08rem; font-weight:800; color:#f8fafc; margin-top:.18rem; }
    .mangrove-metric-v2-sub { font-size:.61rem; color:#64748b; margin-top:.15rem; line-height:1.3; }
    @media(max-width:1000px){ .mangrove-metric-v2-panel{grid-template-columns:repeat(2,minmax(0,1fr));} }
  `;
  document.head.appendChild(style);

  const panel = document.createElement('div');
  panel.id = 'mangrove-metric-v2-panel';
  panel.className = 'mangrove-metric-v2-panel';
  panel.innerHTML = `
    <div class="mangrove-metric-v2-card">
      <div class="mangrove-metric-v2-label">VEGETATION-ONLY NDVI</div>
      <div class="mangrove-metric-v2-value" id="metric-v2-canopy-ndvi">—</div>
      <div class="mangrove-metric-v2-sub">Median NDVI เฉพาะพิกเซล vegetation proxy</div>
    </div>
    <div class="mangrove-metric-v2-card">
      <div class="mangrove-metric-v2-label">NDRE • RED EDGE</div>
      <div class="mangrove-metric-v2-value" id="metric-v2-ndre">—</div>
      <div class="mangrove-metric-v2-sub">สัญญาณ red-edge ของ vegetation • native 20 m</div>
    </div>
    <div class="mangrove-metric-v2-card">
      <div class="mangrove-metric-v2-label">TIDE-RESILIENT VEGETATION PROXY</div>
      <div class="mangrove-metric-v2-value" id="metric-v2-cover">—</div>
      <div class="mangrove-metric-v2-sub">NDVI &gt; 0.25 หรือ MFI &gt; 0 ภายในแปลง</div>
    </div>
    <div class="mangrove-metric-v2-card">
      <div class="mangrove-metric-v2-label">OPEN WATER</div>
      <div class="mangrove-metric-v2-value" id="metric-v2-water">—</div>
      <div class="mangrove-metric-v2-sub">MNDWI water ที่ไม่มี vegetation/MFI signal</div>
    </div>
    <div class="mangrove-metric-v2-card">
      <div class="mangrove-metric-v2-label">OBSERVATION QA</div>
      <div class="mangrove-metric-v2-value" id="metric-v2-qa">—</div>
      <div class="mangrove-metric-v2-sub" id="metric-v2-qa-sub">clear pixels • scenes</div>
    </div>`;
  chartBox.appendChild(panel);
}

function renderMangroveMetricV2() {
  ensureMangroveMetricPanel();
  const item = activePlot?.timeseries?.[currentMonthIndex];
  if (!item) return;

  const set = (id, text) => {
    const element = document.getElementById(id);
    if (element) element.textContent = text;
  };

  set('metric-v2-canopy-ndvi', fmtMetric(item.canopy_ndvi_median, 3));
  set('metric-v2-ndre', fmtMetric(item.ndre_median, 3));
  set('metric-v2-cover', fmtMetric(item.vegetation_coverage_proxy_pct, 1, '%'));
  set('metric-v2-water', fmtMetric(item.open_water_pct, 1, '%'));
  set('metric-v2-qa', fmtMetric(item.clear_pixel_pct, 0, '%'));
  set('metric-v2-qa-sub', `${item.scenes_used || 0} scene(s) • ${item.status || 'no_data'}`);

  const proxyCard = document.getElementById('kpi-plot-canopy-pct')?.parentElement;
  if (proxyCard) {
    const label = proxyCard.querySelector('.kpi-label');
    const sub = proxyCard.querySelector('.kpi-sub');
    if (label) label.textContent = 'Tide-resilient Vegetation Proxy';
    if (sub) sub.textContent = 'NDVI > 0.25 หรือ MFI > 0; แยก open water ออกต่างหาก';
  }

  const subtitle = document.querySelector('.chart-box-subtitle');
  if (subtitle) {
    subtitle.textContent = 'NDVI = ความเขียวของทั้งแปลง • Vegetation Proxy ใช้ NDVI + Mangrove Forest Index เพื่อลดผลจากน้ำขึ้น • ไม่มี interpolation';
  }

  if (plotNdviChart?.data?.datasets?.[1]) {
    plotNdviChart.data.datasets[1].label = 'Tide-resilient Vegetation Proxy (NDVI or MFI)';
    plotNdviChart.update('none');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  ensureMangroveMetricPanel();

  const watchIds = ['kpi-current-plot-name', 'playback-date-display'];
  const observer = new MutationObserver(() => setTimeout(renderMangroveMetricV2, 0));
  watchIds.forEach(id => {
    const node = document.getElementById(id);
    if (node) observer.observe(node, { childList: true, characterData: true, subtree: true });
  });

  document.getElementById('month-slider')?.addEventListener('input', () => setTimeout(renderMangroveMetricV2, 0));
  setTimeout(renderMangroveMetricV2, 800);
});
