// PDD22 production adapter — authoritative participating polygons + cleaned Sentinel-2 + FCD V3.
(() => {
  const PDD_ASSET_VERSION = '20260826-pdd22-v3';
  const PDD_FCD_MONTHS = new Set(['2024-03','2025-03','2026-03','2026-08']);
  let pddFcdLoaded = false;

  function pddImageUrl(plot, prefix, month) {
    return `data/pdd22_satellite/plots/${encodeURIComponent(plot.code)}/${month}/${prefix}.png?v=${PDD_ASSET_VERSION}`;
  }

  function pddFcdUrl(plot, month) {
    return `data/pdd22_v3/maps/${encodeURIComponent(plot.code)}/fcd_${month}.png?v=${PDD_ASSET_VERSION}`;
  }

  function findFcd(plot, month) {
    return Array.isArray(plot?.fcd_observations)
      ? plot.fcd_observations.find(item => item.month === month) || null
      : null;
  }

  loadData = async function() {
    const catalogResponse = await fetch(`data/pdd22/plots_catalog.json?v=${PDD_ASSET_VERSION}`, { cache:'no-store' });
    if (!catalogResponse.ok) throw new Error(`PDD22 catalog: HTTP ${catalogResponse.status}`);
    const catalog = await catalogResponse.json();
    if (!Array.isArray(catalog) || catalog.length !== 22) throw new Error('PDD22 catalog must contain exactly 22 plots');

    const total = catalog.reduce((sum, p) => sum + Number(p.area_rai || 0), 0);
    if (Math.abs(total - 6775.53) > 0.02) throw new Error(`PDD22 area mismatch: ${total}`);

    const metadata = await Promise.all(catalog.map(async plot => {
      const response = await fetch(`data/pdd22_satellite/plots/${encodeURIComponent(plot.code)}/metadata.json?v=${PDD_ASSET_VERSION}`, { cache:'no-store' });
      if (!response.ok) throw new Error(`${plot.code} metadata: HTTP ${response.status}`);
      return response.json();
    }));
    const metaByCode = new Map(metadata.map(meta => [meta.plot_code, meta]));

    let fcdByCode = new Map();
    try {
      const response = await fetch(`data/pdd22_v3/plots_result.json?v=${PDD_ASSET_VERSION}`, { cache:'no-store' });
      if (response.ok) {
        const payload = await response.json();
        if (Array.isArray(payload)) {
          fcdByCode = new Map(payload.map(item => [item.code, item]));
          pddFcdLoaded = payload.length === 22;
        }
      }
    } catch (error) {
      console.warn('FCD V3 unavailable:', error);
    }

    plotsCatalog = catalog.map(plot => ({
      ...plot,
      name: `แปลง ${plot.code}`,
    }));

    allPlotsData = plotsCatalog.map(plot => {
      const meta = metaByCode.get(plot.code);
      const obsByMonth = new Map((meta?.observations || []).map(obs => [obs.month, obs]));
      const timeseries = MILESTONE_MONTHS.map(month => {
        const obs = obsByMonth.get(month);
        const stats = obs?.stats || {};
        return {
          ...parseMonthKey(month),
          mean_ndvi_inside: isFiniteNumber(stats.mean_ndvi) ? stats.mean_ndvi : null,
          median_ndvi_inside: isFiniteNumber(stats.median_ndvi) ? stats.median_ndvi : null,
          vegetation_coverage_proxy_pct: isFiniteNumber(stats.green_proxy_fraction) ? stats.green_proxy_fraction * 100 : null,
          scenes_used: Number.isInteger(obs?.scenes_used_count) ? obs.scenes_used_count : 0,
          clear_pixel_pct: isFiniteNumber(obs?.coverage_pct) ? obs.coverage_pct : null,
          status: obs?.qa || 'NO_DATA',
          qa: obs?.qa || 'NO_DATA',
          analysis_mode: obs?.analysis_mode || 'no_data',
          source: meta?.source || 'Microsoft Planetary Computer / Sentinel-2 L2A',
          scene_ids: Array.isArray(obs?.selected_scene_ids) ? obs.selected_scene_ids : [],
        };
      });
      const first = timeseries[0]?.mean_ndvi_inside;
      const current = timeseries[11]?.mean_ndvi_inside;
      const gain = isFiniteNumber(first) && isFiniteNumber(current) ? current - first : null;
      const fcd = fcdByCode.get(plot.code);
      return {
        ...plot,
        timeseries,
        initial_ndvi: first,
        current_ndvi: current,
        gain_ndvi: gain,
        growth_pct: isFiniteNumber(gain) && Math.abs(first) >= 0.05 ? gain / Math.abs(first) * 100 : null,
        current_vegetation_proxy_pct: timeseries[11]?.vegetation_coverage_proxy_pct ?? null,
        data_quality: 'pdd22_cleaned_scene_dataset',
        fcd_observations: fcd?.observations || [],
      };
    });
    verifiedDatasetLoaded = true;
  };

  imageBoundsForPlot = function(plot) {
    const b = plot.bounds;
    return [[b[1] - IMAGE_BUFFER_DEG, b[0] - IMAGE_BUFFER_DEG],[b[3] + IMAGE_BUFFER_DEG, b[2] + IMAGE_BUFFER_DEG]];
  };

  const baseUpdateStaticCopy = updateStaticCopy;
  updateStaticCopy = function() {
    baseUpdateStaticCopy();
    const title = document.querySelector('.brand-title');
    if (title) title.textContent = 'ระบบติดตามพื้นที่โครงการ PDD22 ป่าชายเลน';
    const subtitle = document.querySelector('.brand-subtitle');
    if (subtitle) subtitle.textContent = '22 PDD participating plots • 6,775.53 ไร่ • Sentinel-2 L2A cleaned observations • FCD Green / Yellow / Red screening';
    const pills = document.querySelectorAll('.header-meta .meta-pill');
    if (pills[0]) pills[0].innerHTML = '<span class="pill-dot"></span> 22 แปลง PDD (6,775.53 ไร่)';
    if (pills[1]) pills[1].textContent = 'PDD participating boundary only';
    if (pills[2]) pills[2].textContent = '12 Sentinel observation months + FCD V3';
    const chartBadge = document.querySelector('.chart-badge-tag');
    if (chartBadge) chartBadge.textContent = pddFcdLoaded ? 'PDD22 cleaned + FCD V3' : 'PDD22 cleaned satellite';
    ensureFcdUI();
    ensureFcdButton();
    const heads = document.querySelectorAll('#plots-data-table thead th');
    if (heads[7]) heads[7].textContent = 'FCD ส.ค. 2026 (G/Y/R ไร่)';
  };

  function ensureFcdButton() {
    const group = document.querySelector('.band-btn-group');
    if (!group || group.querySelector('[data-layer="fcd"]')) return;
    const button = document.createElement('button');
    button.className = 'band-btn';
    button.dataset.layer = 'fcd';
    button.textContent = 'FCD เขียว / เหลือง / แดง';
    button.onclick = () => setPlotMapLayer('fcd');
    group.appendChild(button);
  }

  function ensureFcdUI() {
    if (document.getElementById('pdd-fcd-panel')) return;
    const kpis = document.querySelector('.national-kpi-grid');
    if (!kpis) return;
    const panel = document.createElement('section');
    panel.id = 'pdd-fcd-panel';
    panel.className = 'chart-box';
    panel.style.marginBottom = '16px';
    panel.innerHTML = `
      <div class="chart-header-row">
        <div>
          <h3 class="chart-box-title">Forest Canopy Density — Green / Yellow / Red</h3>
          <p class="chart-box-subtitle" id="pdd-fcd-subtitle">PDD-equivalent Sentinel-2 screening; พื้นที่เทียบเต็มแปลงแสดงเฉพาะ QA GOOD ≥95%</p>
        </div>
        <div class="chart-badge-tag">FCD V3</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:14px">
        <div class="kpi-card"><div class="kpi-label">เขียว • High</div><div class="kpi-value" id="fcd-green-value">—</div><div class="kpi-sub">FCD-equivalent high canopy</div></div>
        <div class="kpi-card"><div class="kpi-label">เหลือง • Medium</div><div class="kpi-value" id="fcd-yellow-value">—</div><div class="kpi-sub">FCD-equivalent medium canopy</div></div>
        <div class="kpi-card"><div class="kpi-label">แดง • Low</div><div class="kpi-value" id="fcd-red-value">—</div><div class="kpi-sub">FCD-equivalent low canopy</div></div>
        <div class="kpi-card"><div class="kpi-label">QA / Coverage</div><div class="kpi-value" id="fcd-qa-value">—</div><div class="kpi-sub" id="fcd-coverage-value">—</div></div>
      </div>`;
    kpis.insertAdjacentElement('afterend', panel);
  }

  function updateFcdPanel() {
    ensureFcdUI();
    if (!activePlot) return;
    const month = activePlot.timeseries[currentMonthIndex]?.month;
    const fcd = findFcd(activePlot, month);
    const green = document.getElementById('fcd-green-value');
    const yellow = document.getElementById('fcd-yellow-value');
    const red = document.getElementById('fcd-red-value');
    const qa = document.getElementById('fcd-qa-value');
    const coverage = document.getElementById('fcd-coverage-value');
    const subtitle = document.getElementById('pdd-fcd-subtitle');
    if (!fcd) {
      if (green) green.textContent = '—';
      if (yellow) yellow.textContent = '—';
      if (red) red.textContent = '—';
      if (qa) qa.textContent = 'ไม่มี FCD เดือนนี้';
      if (coverage) coverage.textContent = 'FCD มีที่ มี.ค. 2024 / 2025 / 2026 และ ส.ค. 2026';
      if (subtitle) subtitle.textContent = `${activePlot.code} • ${month} • Sentinel data available; FCD not scheduled for this month`;
      return;
    }
    const equivalent = fcd.qa === 'GOOD' && isFiniteNumber(fcd.green_rai);
    const g = equivalent ? fcd.green_rai : fcd.green_observed_rai;
    const y = equivalent ? fcd.yellow_rai : fcd.yellow_observed_rai;
    const r = equivalent ? fcd.red_rai : fcd.red_observed_rai;
    if (green) green.textContent = isFiniteNumber(g) ? `${g.toFixed(2)} ไร่` : '—';
    if (yellow) yellow.textContent = isFiniteNumber(y) ? `${y.toFixed(2)} ไร่` : '—';
    if (red) red.textContent = isFiniteNumber(r) ? `${r.toFixed(2)} ไร่` : '—';
    if (qa) qa.textContent = fcd.qa || '—';
    if (coverage) coverage.textContent = `Coverage ${Number(fcd.coverage_pct || 0).toFixed(1)}% • ${fcd.analysis_mode}`;
    if (subtitle) subtitle.textContent = `${activePlot.code} • ${month} • ${equivalent ? 'PDD-equivalent area' : 'พื้นที่ที่สังเกตได้เท่านั้น — ไม่ extrapolate เพราะ QA ไม่ถึง GOOD'}`;

    const fourth = document.getElementById('kpi-plot-canopy-pct');
    if (fourth) fourth.textContent = equivalent && isFiniteNumber(g) ? `G ${g.toFixed(1)} • Y ${y.toFixed(1)} • R ${r.toFixed(1)}` : `${fcd.qa}`;
    const fourthLabel = fourth?.parentElement?.querySelector('.kpi-label');
    if (fourthLabel) fourthLabel.textContent = 'FCD เขียว / เหลือง / แดง';
  }

  updateGeeOverlay = async function() {
    if (!activePlot || !plotSatelliteMap || currentPlotLayerKey === 'esri') return;
    const item = activePlot.timeseries[currentMonthIndex];
    if (!item) return;
    const url = currentPlotLayerKey === 'fcd'
      ? pddFcdUrl(activePlot, item.month)
      : pddImageUrl(activePlot, currentPlotLayerKey === 'gee_ndvi' ? 'ndvi' : 'rgb', item.month);
    const token = ++sentinelSwapToken;
    try { await preloadImage(url); }
    catch (error) {
      if (token !== sentinelSwapToken) return;
      if (currentPlotLayerKey === 'fcd' && !PDD_FCD_MONTHS.has(item.month)) return;
      console.warn('Overlay unavailable', url, error);
      return;
    }
    if (token !== sentinelSwapToken) return;
    const next = L.imageOverlay(url, imageBoundsForPlot(activePlot), { opacity:1, interactive:false, className:'sentinel-overlay' });
    next.addTo(plotSatelliteMap);
    if (currentSentinelOverlay && plotSatelliteMap.hasLayer(currentSentinelOverlay)) plotSatelliteMap.removeLayer(currentSentinelOverlay);
    currentSentinelOverlay = next;
  };

  initLeafletThailandMap = function() {
    leafletMap = L.map('thailand-map').setView([9.5,100.2],6);
    L.tileLayer(ESRI_WORLD_IMAGERY,{maxZoom:19,attribution:'Tiles &copy; Esri'}).addTo(leafletMap);
    fetch(`data/pdd22/plots.geojson?v=${PDD_ASSET_VERSION}`,{cache:'no-store'}).then(response => response.json()).then(geojson => {
      thailandGeojsonLayer = L.geoJSON(geojson,{
        style:{color:'#10b981',weight:2,opacity:.95,fillColor:'#10b981',fillOpacity:.04},
        onEachFeature:(feature,layer) => {
          const p = feature.properties;
          layer.bindPopup(`<div class="popup-title">${escapeHtml(p.code || p.name)}</div><div class="popup-meta">จังหวัด: <strong>${escapeHtml(p.province)}</strong> | พื้นที่ PDD: <strong>${Number(p.area_rai).toFixed(2)} ไร่</strong></div><button class="popup-btn" onclick="selectPlot(${p.id}); switchWorkspaceTab('detail');">ดูแปลงนี้</button>`);
          layer.on('click',() => selectPlot(p.id));
        }
      }).addTo(leafletMap);
    });
  };

  updateCompareView = function() {
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
    const leftUrl = pddImageUrl(activePlot,leftPrefix,leftItem.month);
    const rightUrl = pddImageUrl(activePlot,rightPrefix,rightItem.month);
    compareLeftOverlay = replaceCompareLayer(compareLeftMap,compareLeftOverlay,leftUrl,activePlot);
    compareRightOverlay = replaceCompareLayer(compareRightMap,compareRightOverlay,rightUrl,activePlot);
    const showBoundary = document.getElementById('comp-boundary-toggle')?.checked !== false;
    compareLeftBoundary = replaceCompareBoundary(compareLeftMap,compareLeftBoundary,activePlot,showBoundary);
    compareRightBoundary = replaceCompareBoundary(compareRightMap,compareRightBoundary,activePlot,showBoundary);
    const bounds = L.geoJSON({type:'Feature',properties:{},geometry:activePlot.geometry}).getBounds();
    if (bounds.isValid()) {
      const options={padding:[34,34],maxZoom:17,animate:false};
      compareLeftMap.fitBounds(bounds,options); compareRightMap.fitBounds(bounds,options);
    }
    const leftNdvi=leftItem.mean_ndvi_inside, rightNdvi=rightItem.mean_ndvi_inside;
    const statText=document.getElementById('comp-in-stat-text'), gainPill=document.getElementById('comp-gain-pill');
    if (isFiniteNumber(leftNdvi) && isFiniteNumber(rightNdvi)) {
      const diff=rightNdvi-leftNdvi;
      statText.innerHTML=`Mean NDVI: <strong>${leftNdvi.toFixed(3)}</strong> ➔ <strong>${rightNdvi.toFixed(3)}</strong>`;
      gainPill.textContent=`${diff>=0?'+':''}${diff.toFixed(3)}`;
    } else { statText.textContent='ข้อมูลช่วงนี้ไม่ผ่าน QA หรือไม่มีภาพจริง'; gainPill.textContent='QA'; }
  };

  initTable = function(plots) {
    const tbody = document.getElementById('table-body');
    document.getElementById('table-count-label').textContent = `PDD22 ทั้งหมด ${plots.length} แปลง`;
    tbody.innerHTML = '';
    plots.forEach(plot => {
      const currentFcd = findFcd(plot,'2026-08');
      const fcdText = currentFcd?.qa === 'GOOD' && isFiniteNumber(currentFcd.green_rai)
        ? `G ${currentFcd.green_rai.toFixed(1)} / Y ${currentFcd.yellow_rai.toFixed(1)} / R ${currentFcd.red_rai.toFixed(1)}`
        : (currentFcd?.qa || '—');
      const row = document.createElement('tr');
      row.innerHTML = `<td><strong>${escapeHtml(plot.code)}</strong></td><td>${escapeHtml(plot.name)}</td><td><span class="p-prov-tag">${escapeHtml(plot.province)}</span></td><td>${Number(plot.area_rai).toFixed(2)}</td><td>${isFiniteNumber(plot.initial_ndvi)?plot.initial_ndvi.toFixed(3):'—'}</td><td>${isFiniteNumber(plot.current_ndvi)?plot.current_ndvi.toFixed(3):'—'}</td><td><strong>${isFiniteNumber(plot.gain_ndvi)?`${plot.gain_ndvi>=0?'+':''}${plot.gain_ndvi.toFixed(3)}`:'—'}</strong></td><td>${escapeHtml(fcdText)}</td><td><button class="btn-table-view" data-plot-id="${plot.id}">ดูรายละเอียด</button></td>`;
      row.querySelector('.btn-table-view').addEventListener('click',()=>{selectPlot(plot.id);switchWorkspaceTab('detail');});
      tbody.appendChild(row);
    });
  };

  exportPlotsCSV = function() {
    if (!allPlotsData.length) return;
    const headers=['Plot Code','Province','PDD Area Rai','NDVI Sep 2023','NDVI Aug 2026','NDVI Gain','FCD Aug 2026 QA','Green Rai','Yellow Rai','Red Rai'];
    const rows=allPlotsData.map(plot=>{
      const f=findFcd(plot,'2026-08');
      return [plot.code,plot.province,plot.area_rai,plot.initial_ndvi??'',plot.current_ndvi??'',plot.gain_ndvi??'',f?.qa??'',f?.green_rai??'',f?.yellow_rai??'',f?.red_rai??''];
    });
    const csv='\uFEFF'+[headers.join(','),...rows.map(row=>row.map(v=>`"${String(v).replaceAll('"','""')}"`).join(','))].join('\n');
    const blob=new Blob([csv],{type:'text/csv;charset=utf-8;'}); const url=URL.createObjectURL(blob);
    const anchor=document.createElement('a'); anchor.href=url; anchor.download=`pdd22_fcd_${new Date().toISOString().slice(0,10)}.csv`; anchor.click(); URL.revokeObjectURL(url);
  };

  const baseSetMonthIndex = setMonthIndex;
  setMonthIndex = function(index) { baseSetMonthIndex(index); updateFcdPanel(); };
  const baseSelectPlot = selectPlot;
  selectPlot = function(id) { baseSelectPlot(id); updateFcdPanel(); };
})();
