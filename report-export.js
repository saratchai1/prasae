// Prasae per-plot report export.
// Exports only the current verified 12-date data already loaded by app.js.
// No interpolation, synthetic metrics, or nearest-date substitution is introduced here.

(() => {
  const REPORT_VERSION = '20260818-2200';
  const XLSX_CDN = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';
  const HTML2PDF_CDN = 'https://cdn.jsdelivr.net/npm/html2pdf.js@0.10.1/dist/html2pdf.bundle.min.js';
  const dependencyPromises = new Map();

  function loadScriptOnce(key, url, globalName) {
    if (globalThis[globalName]) return Promise.resolve(globalThis[globalName]);
    if (dependencyPromises.has(key)) return dependencyPromises.get(key);
    const promise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = url;
      script.async = true;
      script.onload = () => globalThis[globalName] ? resolve(globalThis[globalName]) : reject(new Error(`${globalName} did not initialize`));
      script.onerror = () => reject(new Error(`Unable to load ${url}`));
      document.head.appendChild(script);
    });
    dependencyPromises.set(key, promise);
    return promise;
  }

  const isObserved = item => item && ['observed_single_scene', 'observed_monthly_composite'].includes(item.status);
  const numOrBlank = value => isFiniteNumber(value) ? value : '';
  const pctOrDash = value => isFiniteNumber(value) ? `${value.toFixed(1)}%` : '—';
  const ndviOrDash = value => isFiniteNumber(value) ? value.toFixed(3) : '—';
  const htmlEscape = value => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

  function reportDateLabel(item) {
    return item ? `${thaiMonths[item.month_num]} ${item.year}` : '—';
  }

  function currentMetricItem(plot) {
    return plot?.timeseries?.[currentMonthIndex] || plot?.timeseries?.findLast?.(isObserved) || null;
  }

  function earliestAndLatestObserved(plot) {
    const observed = (plot?.timeseries || []).filter(isObserved);
    if (!observed.length) return [null, null];
    return [observed[0], observed[observed.length - 1]];
  }

  function safeFilenamePart(value) {
    return String(value || 'plot').replace(/[^a-zA-Z0-9_-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 80) || 'plot';
  }

  function setButtonBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.originalText = button.textContent;
      button.textContent = label;
      button.disabled = true;
    } else {
      button.textContent = button.dataset.originalText || button.textContent;
      button.disabled = false;
    }
  }

  function injectStyles() {
    if (document.getElementById('report-export-styles')) return;
    const style = document.createElement('style');
    style.id = 'report-export-styles';
    style.textContent = `
      .report-export-actions { display:flex; gap:7px; align-items:center; flex-wrap:wrap; }
      .report-export-btn {
        border:1px solid rgba(255,255,255,.12); background:rgba(15,23,42,.85); color:#e2e8f0;
        border-radius:8px; padding:8px 10px; cursor:pointer; font:inherit; font-size:.68rem; font-weight:700;
        white-space:nowrap;
      }
      .report-export-btn:hover:not(:disabled) { border-color:rgba(56,189,248,.65); color:#e0f2fe; }
      .report-export-btn:disabled { opacity:.55; cursor:wait; }
      .report-export-btn.pdf { border-color:rgba(248,113,113,.25); }
      .report-export-btn.xlsx { border-color:rgba(52,211,153,.25); }

      .prasae-report-sheet {
        width:794px; box-sizing:border-box; padding:34px 38px; background:#fff; color:#0f172a;
        font-family:'Sarabun', Arial, sans-serif; font-size:12px; line-height:1.42;
      }
      .prasae-report-header { display:flex; justify-content:space-between; gap:20px; align-items:flex-start; border-bottom:2px solid #0f766e; padding-bottom:14px; }
      .prasae-report-title { font-size:22px; font-weight:800; color:#0f172a; margin:0; }
      .prasae-report-subtitle { margin-top:5px; color:#475569; font-size:11px; }
      .prasae-report-code { color:#0f766e; font-weight:800; font-size:13px; text-align:right; }
      .prasae-report-section { margin-top:18px; }
      .prasae-report-section-title { font-size:13px; font-weight:800; color:#0f172a; margin-bottom:8px; border-left:4px solid #0f766e; padding-left:8px; }
      .prasae-report-meta { display:grid; grid-template-columns:1fr 1fr; gap:5px 18px; color:#334155; }
      .prasae-report-kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
      .prasae-report-kpi { border:1px solid #e2e8f0; border-radius:8px; padding:10px; background:#f8fafc; }
      .prasae-report-kpi-label { font-size:9px; color:#64748b; text-transform:uppercase; font-weight:700; }
      .prasae-report-kpi-value { font-size:18px; color:#0f172a; font-weight:800; margin-top:3px; }
      .prasae-report-kpi-note { font-size:8.5px; color:#94a3b8; margin-top:2px; }
      .prasae-report-chart { width:100%; max-height:240px; object-fit:contain; display:block; border:1px solid #e2e8f0; border-radius:8px; }
      .prasae-report-images { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
      .prasae-report-image-card { border:1px solid #e2e8f0; border-radius:8px; overflow:hidden; background:#0f172a; }
      .prasae-report-image-label { background:#f8fafc; color:#334155; padding:6px 8px; font-size:9px; font-weight:700; }
      .prasae-report-image-card img { width:100%; height:205px; display:block; object-fit:contain; background:#0f172a; }
      .prasae-report-table { width:100%; border-collapse:collapse; table-layout:fixed; font-size:8.2px; }
      .prasae-report-table th { background:#e2e8f0; color:#334155; font-weight:800; padding:5px 3px; border:1px solid #cbd5e1; }
      .prasae-report-table td { padding:4px 3px; border:1px solid #e2e8f0; text-align:center; vertical-align:middle; }
      .prasae-report-table td:first-child { font-weight:700; }
      .prasae-report-method { border:1px solid #bae6fd; background:#f0f9ff; border-radius:8px; padding:9px 10px; color:#334155; font-size:9px; }
      .prasae-report-footer { margin-top:16px; padding-top:8px; border-top:1px solid #e2e8f0; color:#94a3b8; font-size:8px; }
      @media(max-width:900px) { .report-export-actions { width:100%; } }
    `;
    document.head.appendChild(style);
  }

  function injectButtons() {
    injectStyles();
    const toolbar = document.querySelector('#panel-detail .viewer-toolbar');
    if (toolbar && !document.getElementById('report-export-actions')) {
      const actions = document.createElement('div');
      actions.className = 'report-export-actions';
      actions.id = 'report-export-actions';
      actions.innerHTML = `
        <button class="report-export-btn pdf" id="export-plot-pdf" type="button">Export PDF</button>
        <button class="report-export-btn xlsx" id="export-plot-xlsx" type="button">Export Excel</button>`;
      toolbar.appendChild(actions);
      document.getElementById('export-plot-pdf')?.addEventListener('click', exportActivePlotPdf);
      document.getElementById('export-plot-xlsx')?.addEventListener('click', exportActivePlotExcel);
    }
  }

  function summarySheetRows(plot) {
    const item = currentMetricItem(plot);
    const threshold = isFiniteNumber(item?.green_proxy_threshold)
      ? item.green_proxy_threshold
      : (isFiniteNumber(plot.green_proxy_threshold) ? plot.green_proxy_threshold : '');
    return [
      ['Prasae Mangrove Monitoring — Plot Summary', ''],
      ['Generated', new Date().toISOString()],
      ['Plot Code', plot.code || ''],
      ['Plot Name', plot.name || ''],
      ['Province', plot.province || ''],
      ['Area (rai)', numOrBlank(plot.area_rai)],
      ['Centroid Latitude', Array.isArray(plot.centroid) ? plot.centroid[0] : ''],
      ['Centroid Longitude', Array.isArray(plot.centroid) ? plot.centroid[1] : ''],
      ['Selected Observation', item?.month || ''],
      ['Selected Mean NDVI', numOrBlank(item?.mean_ndvi_inside)],
      ['Selected Green Cover Proxy (%)', numOrBlank(item?.vegetation_coverage_proxy_pct)],
      ['Selected Vegetation-only NDVI', numOrBlank(item?.canopy_ndvi_median)],
      ['Selected NDRE', numOrBlank(item?.ndre_median)],
      ['Selected Open Water (%)', numOrBlank(item?.open_water_pct)],
      ['Selected MFI Signal in Water (%)', numOrBlank(item?.submerged_mangrove_signal_pct)],
      ['Selected Clear Pixel (%)', numOrBlank(item?.clear_pixel_pct)],
      ['Green Cover Threshold', threshold],
      ['Calibration Status', item?.green_proxy_calibration_status || plot.green_proxy_calibration_status || ''],
      ['Data Quality', plot.data_quality || ''],
      ['Source', plot.source || item?.source || 'Microsoft Planetary Computer / Sentinel-2 L2A'],
      ['Time Series Contract', '12 declared observation/composite months; no interpolation; no nearest-month substitution; no synthetic fallback'],
      ['Disclaimer', 'Green Cover is a proxy, not field canopy cover, survival rate, tree count, biomass, or carbon stock.']
    ];
  }

  function observationsForExcel(plot) {
    return (plot.timeseries || []).map(item => ({
      Month: item.month,
      Status: item.status || '',
      'Mean NDVI': numOrBlank(item.mean_ndvi_inside),
      'Median NDVI': numOrBlank(item.median_ndvi_inside),
      'NDVI P10': numOrBlank(item.ndvi_p10_inside),
      'NDVI P90': numOrBlank(item.ndvi_p90_inside),
      'Green Cover Proxy (%)': numOrBlank(item.vegetation_coverage_proxy_pct),
      'Vegetation-only NDVI': numOrBlank(item.canopy_ndvi_median),
      NDRE: numOrBlank(item.ndre_median),
      EVI: numOrBlank(item.evi_median),
      'Open Water (%)': numOrBlank(item.open_water_pct),
      'Open Non-vegetated (%)': numOrBlank(item.open_nonvegetated_pct),
      'MFI Signal in Water (%)': numOrBlank(item.submerged_mangrove_signal_pct),
      'Clear Pixel (%)': numOrBlank(item.clear_pixel_pct),
      'Scenes Used': Number.isFinite(item.scenes_used) ? item.scenes_used : '',
      'Green Threshold': numOrBlank(item.green_proxy_threshold),
      'Calibration Status': item.green_proxy_calibration_status || '',
      Source: item.source || ''
    }));
  }

  async function exportActivePlotExcel() {
    const plot = activePlot;
    if (!plot) return;
    const button = document.getElementById('export-plot-xlsx');
    setButtonBusy(button, true, 'Building Excel…');
    try {
      const XLSX = await loadScriptOnce('xlsx', XLSX_CDN, 'XLSX');
      const workbook = XLSX.utils.book_new();
      const summary = XLSX.utils.aoa_to_sheet(summarySheetRows(plot));
      summary['!cols'] = [{ wch: 34 }, { wch: 84 }];
      const observations = XLSX.utils.json_to_sheet(observationsForExcel(plot));
      observations['!cols'] = [
        { wch: 12 }, { wch: 28 }, { wch: 13 }, { wch: 13 }, { wch: 11 }, { wch: 11 },
        { wch: 21 }, { wch: 21 }, { wch: 12 }, { wch: 12 }, { wch: 16 }, { wch: 23 },
        { wch: 23 }, { wch: 16 }, { wch: 12 }, { wch: 17 }, { wch: 28 }, { wch: 50 }
      ];
      XLSX.utils.book_append_sheet(workbook, summary, 'Summary');
      XLSX.utils.book_append_sheet(workbook, observations, 'Observations');
      const filename = `Prasae_${safeFilenamePart(plot.code)}_12dates_${new Date().toISOString().slice(0, 10)}.xlsx`;
      XLSX.writeFile(workbook, filename, { compression: true });
    } catch (error) {
      console.error('Excel export failed:', error);
      alert(`สร้าง Excel ไม่สำเร็จ: ${error.message || error}`);
    } finally {
      setButtonBusy(button, false);
    }
  }

  function imageUrlFor(plot, item) {
    return item ? `data/plots/${plot.id}/rgb_${item.month}.png?v=${REPORT_VERSION}` : '';
  }

  function observationRowsHtml(plot) {
    return (plot.timeseries || []).map(item => {
      const context = typeof observationContext === 'function' ? observationContext(item) : { label: '' };
      return `
        <tr>
          <td>${htmlEscape(item.month)}</td>
          <td>${htmlEscape(item.status || '—')}</td>
          <td>${ndviOrDash(item.mean_ndvi_inside)}</td>
          <td>${pctOrDash(item.vegetation_coverage_proxy_pct)}</td>
          <td>${ndviOrDash(item.canopy_ndvi_median)}</td>
          <td>${ndviOrDash(item.ndre_median)}</td>
          <td>${pctOrDash(item.open_water_pct)}</td>
          <td>${pctOrDash(item.clear_pixel_pct)}</td>
          <td>${Number.isFinite(item.scenes_used) ? item.scenes_used : '—'}</td>
          <td>${htmlEscape(context.label || '')}</td>
        </tr>`;
    }).join('');
  }

  function chartDataUrl() {
    try {
      return plotNdviChart?.toBase64Image?.('image/png', 1) || '';
    } catch (_) {
      return '';
    }
  }

  function buildPdfReportElement(plot) {
    const selected = currentMetricItem(plot);
    const [before, after] = earliestAndLatestObserved(plot);
    const calibrationStatus = selected?.green_proxy_calibration_status || plot.green_proxy_calibration_status || 'DEFAULT / UNKNOWN';
    const threshold = isFiniteNumber(selected?.green_proxy_threshold)
      ? selected.green_proxy_threshold.toFixed(3)
      : (isFiniteNumber(plot.green_proxy_threshold) ? plot.green_proxy_threshold.toFixed(3) : '—');
    const chart = chartDataUrl();

    const container = document.createElement('div');
    container.style.position = 'fixed';
    container.style.left = '-12000px';
    container.style.top = '0';
    container.style.zIndex = '-1000';
    container.innerHTML = `
      <article class="prasae-report-sheet" id="prasae-pdf-report-sheet">
        <header class="prasae-report-header">
          <div>
            <h1 class="prasae-report-title">รายงานติดตามแปลงฟื้นฟูป่าชายเลน</h1>
            <div class="prasae-report-subtitle">Prasae Mangrove Monitoring • Sentinel-2 L2A • observed-only 12-date monitoring</div>
          </div>
          <div class="prasae-report-code">${htmlEscape(plot.code)}<br><span style="color:#64748b;font-size:9px;font-weight:600">${htmlEscape(plot.province)}</span></div>
        </header>

        <section class="prasae-report-section">
          <div class="prasae-report-section-title">ข้อมูลแปลง</div>
          <div class="prasae-report-meta">
            <div><strong>ชื่อ:</strong> ${htmlEscape(plot.name)}</div>
            <div><strong>พื้นที่:</strong> ${Number(plot.area_rai || 0).toLocaleString('th-TH', { maximumFractionDigits: 2 })} ไร่</div>
            <div><strong>จังหวัด:</strong> ${htmlEscape(plot.province)}</div>
            <div><strong>พิกัดกลาง:</strong> ${Array.isArray(plot.centroid) ? `${plot.centroid[0].toFixed(5)}, ${plot.centroid[1].toFixed(5)}` : '—'}</div>
            <div><strong>Observation ที่เลือก:</strong> ${htmlEscape(selected?.month || '—')}</div>
            <div><strong>Green threshold:</strong> ${threshold} • ${htmlEscape(calibrationStatus)}</div>
          </div>
        </section>

        <section class="prasae-report-section">
          <div class="prasae-report-section-title">ค่าจาก observation ที่เลือก</div>
          <div class="prasae-report-kpis">
            <div class="prasae-report-kpi"><div class="prasae-report-kpi-label">Mean NDVI</div><div class="prasae-report-kpi-value">${ndviOrDash(selected?.mean_ndvi_inside)}</div><div class="prasae-report-kpi-note">whole-plot • water-sensitive</div></div>
            <div class="prasae-report-kpi"><div class="prasae-report-kpi-label">Green Cover Proxy</div><div class="prasae-report-kpi-value">${pctOrDash(selected?.vegetation_coverage_proxy_pct)}</div><div class="prasae-report-kpi-note">threshold ${threshold}</div></div>
            <div class="prasae-report-kpi"><div class="prasae-report-kpi-label">NDRE</div><div class="prasae-report-kpi-value">${ndviOrDash(selected?.ndre_median)}</div><div class="prasae-report-kpi-note">red-edge diagnostic</div></div>
            <div class="prasae-report-kpi"><div class="prasae-report-kpi-label">Open Water</div><div class="prasae-report-kpi-value">${pctOrDash(selected?.open_water_pct)}</div><div class="prasae-report-kpi-note">MNDWI context</div></div>
          </div>
        </section>

        ${chart ? `<section class="prasae-report-section"><div class="prasae-report-section-title">แนวโน้ม 12 observation dates</div><img class="prasae-report-chart" src="${chart}" alt="12-date chart"></section>` : ''}

        <section class="prasae-report-section">
          <div class="prasae-report-section-title">ภาพ Sentinel-2 ก่อน / หลังที่มี observation จริง</div>
          <div class="prasae-report-images">
            <div class="prasae-report-image-card"><div class="prasae-report-image-label">Before • ${htmlEscape(before?.month || 'No data')}</div>${before ? `<img src="${imageUrlFor(plot, before)}" alt="Before Sentinel-2">` : '<div style="height:205px;color:#94a3b8;display:flex;align-items:center;justify-content:center">No observed image</div>'}</div>
            <div class="prasae-report-image-card"><div class="prasae-report-image-label">After • ${htmlEscape(after?.month || 'No data')}</div>${after ? `<img src="${imageUrlFor(plot, after)}" alt="After Sentinel-2">` : '<div style="height:205px;color:#94a3b8;display:flex;align-items:center;justify-content:center">No observed image</div>'}</div>
          </div>
        </section>

        <section class="prasae-report-section">
          <div class="prasae-report-section-title">Observed 12-date statistics</div>
          <table class="prasae-report-table">
            <thead><tr><th>Month</th><th>Status</th><th>NDVI</th><th>Green</th><th>Veg NDVI</th><th>NDRE</th><th>Water</th><th>Clear</th><th>Scenes</th><th>Context</th></tr></thead>
            <tbody>${observationRowsHtml(plot)}</tbody>
          </table>
        </section>

        <section class="prasae-report-section">
          <div class="prasae-report-method"><strong>Method / limitations:</strong> ระบบใช้ Sentinel-2 L2A เฉพาะ 12 observation/composite months ที่ประกาศไว้ ไม่มี interpolation, nearest-month substitution หรือ synthetic fallback. Green Cover เป็น proxy ไม่ใช่ field canopy cover, survival rate, tree count, biomass หรือ carbon stock. ต้องอ่าน Open Water และ QA ควบคู่ก่อนสรุปการเปลี่ยนแปลง.</div>
        </section>
        <footer class="prasae-report-footer">Generated ${new Date().toLocaleString('th-TH')} • Source: Microsoft Planetary Computer / Sentinel-2 L2A • Report module ${REPORT_VERSION}</footer>
      </article>`;
    document.body.appendChild(container);
    return { container, sheet: container.querySelector('#prasae-pdf-report-sheet') };
  }

  async function waitForImages(root) {
    const images = [...root.querySelectorAll('img')];
    await Promise.all(images.map(image => {
      if (image.complete) return Promise.resolve();
      return new Promise(resolve => {
        image.onload = resolve;
        image.onerror = resolve;
      });
    }));
  }

  async function exportActivePlotPdf() {
    const plot = activePlot;
    if (!plot) return;
    const button = document.getElementById('export-plot-pdf');
    setButtonBusy(button, true, 'Building PDF…');
    let report = null;
    try {
      await loadScriptOnce('html2pdf', HTML2PDF_CDN, 'html2pdf');
      report = buildPdfReportElement(plot);
      await waitForImages(report.sheet);
      await document.fonts?.ready;
      const filename = `Prasae_${safeFilenamePart(plot.code)}_report_${new Date().toISOString().slice(0, 10)}.pdf`;
      await globalThis.html2pdf()
        .set({
          margin: 0,
          filename,
          image: { type: 'jpeg', quality: 0.96 },
          html2canvas: { scale: 2, useCORS: true, backgroundColor: '#ffffff', logging: false },
          jsPDF: { unit: 'px', format: [794, 1123], orientation: 'portrait', hotfixes: ['px_scaling'] },
          pagebreak: { mode: ['css', 'legacy'], avoid: ['.prasae-report-kpi', '.prasae-report-image-card'] }
        })
        .from(report.sheet)
        .save();
    } catch (error) {
      console.error('PDF export failed:', error);
      alert(`สร้าง PDF ไม่สำเร็จ: ${error.message || error}`);
    } finally {
      report?.container?.remove();
      setButtonBusy(button, false);
    }
  }

  document.addEventListener('DOMContentLoaded', injectButtons);
})();
