// Site-calibrated Green Cover presentation v4.1.
// Loaded after metrics-v2.js; keeps map/selection/compare state untouched.

const METRIC_V4_VERSION = '20260818-0020';
const baseNormalizePlotV4 = normalizePlot;

normalizePlot = function(plot, catalogPlot) {
  const normalized = baseNormalizePlotV4(plot, catalogPlot);
  const rawByMonth = new Map((plot.timeseries || []).map(item => [item.month, item]));

  normalized.timeseries = normalized.timeseries.map(item => {
    const raw = rawByMonth.get(item.month) || {};
    return {
      ...item,
      green_proxy_threshold: isFiniteNumber(raw.green_proxy_threshold)
        ? raw.green_proxy_threshold
        : (isFiniteNumber(plot.green_proxy_threshold) ? plot.green_proxy_threshold : 0.25),
      green_proxy_calibration_status:
        raw.green_proxy_calibration_status || plot.green_proxy_calibration_status || 'DEFAULT_UNCALIBRATED',
      green_proxy_calibration_source:
        raw.green_proxy_calibration_source || plot.green_proxy_calibration_source || 'portfolio conservative default'
    };
  });

  normalized.green_proxy_threshold = isFiniteNumber(plot.green_proxy_threshold)
    ? plot.green_proxy_threshold : 0.25;
  normalized.green_proxy_calibration_status =
    plot.green_proxy_calibration_status || 'DEFAULT_UNCALIBRATED';
  normalized.green_proxy_calibration_source =
    plot.green_proxy_calibration_source || 'portfolio conservative default';
  return normalized;
};

function ensureCalibrationCardV4() {
  const panel = document.getElementById('mangrove-metric-v2-panel');
  if (!panel || document.getElementById('metric-v4-calibration')) return;

  const card = document.createElement('div');
  card.className = 'mangrove-metric-v2-card';
  card.innerHTML = `
    <div class="mangrove-metric-v2-label">GREEN COVER CALIBRATION</div>
    <div class="mangrove-metric-v2-value" id="metric-v4-calibration">—</div>
    <div class="mangrove-metric-v2-sub" id="metric-v4-calibration-sub">threshold provenance</div>`;
  panel.appendChild(card);
}

const baseRenderMangroveMetricV4 = renderMangroveMetricV2;

renderMangroveMetricV2 = function() {
  baseRenderMangroveMetricV4();
  ensureCalibrationCardV4();

  const item = activePlot?.timeseries?.[currentMonthIndex];
  if (!item) return;

  const threshold = isFiniteNumber(item.green_proxy_threshold)
    ? item.green_proxy_threshold
    : 0.25;
  const status = item.green_proxy_calibration_status || 'DEFAULT_UNCALIBRATED';
  const source = item.green_proxy_calibration_source || 'portfolio conservative default';
  const calibrated = status === 'PROMOTED_DRONE_CALIBRATED';
  const thresholdText = threshold.toFixed(3);

  const set = (id, text) => {
    const element = document.getElementById(id);
    if (element) element.textContent = text;
  };

  set('metric-v4-calibration', calibrated ? `NDVI > ${thresholdText}` : `DEFAULT ${thresholdText}`);
  set(
    'metric-v4-calibration-sub',
    calibrated
      ? `DRONE CALIBRATED • spatial holdout • ${source}`
      : `UNCALIBRATED SITE • ${source}`
  );

  const proxyCard = document.getElementById('kpi-plot-canopy-pct')?.parentElement;
  if (proxyCard) {
    const label = proxyCard.querySelector('.kpi-label');
    const sub = proxyCard.querySelector('.kpi-sub');
    if (label) {
      label.textContent = calibrated
        ? 'Drone-calibrated Green Cover Proxy'
        : 'Conservative Green Cover Proxy';
    }
    if (sub) {
      sub.textContent = calibrated
        ? `NDVI > ${thresholdText} • 13-STC drone-density reference + spatial holdout`
        : `NDVI > ${thresholdText} • conservative default; ยังไม่มี site-specific calibration`;
    }
  }

  const panel = document.getElementById('mangrove-metric-v2-panel');
  const coverCard = panel?.querySelector('#metric-v2-cover')?.parentElement;
  if (coverCard) {
    const sub = coverCard.querySelector('.mangrove-metric-v2-sub');
    if (sub) {
      sub.textContent = calibrated
        ? `NDVI > ${thresholdText} • drone-calibrated for this site`
        : `NDVI > ${thresholdText} • conservative default`;
    }
  }

  const subtitle = document.querySelector('.chart-box-subtitle');
  if (subtitle) {
    subtitle.textContent = calibrated
      ? `Green Cover ใช้ NDVI > ${thresholdText} ที่ calibrate จาก 13-STC drone tree-density และ spatial holdout • Open Water ใช้แยกผลน้ำ • MFI เป็น diagnostic • ไม่มี interpolation`
      : `Green Cover ใช้ NDVI > ${thresholdText} แบบ conservative • Open Water ช่วยแยกผลน้ำ • MFI เป็น diagnostic • ไม่มี interpolation`;
  }

  if (plotNdviChart?.data?.datasets?.[1]) {
    plotNdviChart.data.datasets[1].label = calibrated
      ? `Drone-calibrated Green Cover (NDVI > ${thresholdText})`
      : `Conservative Green Cover (NDVI > ${thresholdText})`;
    plotNdviChart.update('none');
  }
};
