// PDD22 production adapter — authoritative participating polygons + cleaned Sentinel-2 + FCD V3.
(() => {
  const PDD22_VERSION = '20260826-1405';
  const FCD_MONTHS = new Set(['2024-03', '2025-03', '2026-03', '2026-08']);
  let portfolioRows = [];

  function n(value) {
    if (value === null || value === undefined || value === '') return null;
    const x = Number(value);
    return Number.isFinite(x) ? x : null;
  }

  function parseSimpleCsv(text) {
    const lines = text.replace(/^\uFEFF/, '').trim().split(/\r?\n/).filter(Boolean);
    if (!lines.length) return [];
    const header = lines[0].split(',');
    return lines.slice(1).map(line => {
      const cols = line.split(',');
      const out = {};
      header.forEach((key, i) => { out[key] = cols[i] ?? ''; });
      return out;
    });
  }

  function fcdObservation(plot, month) {
    return plot?.fcd_by_month?.[month] || null;
  }

  function latestGoodFcd(plot) {
    return fcdObservation(plot, '2026-08')?.qa === 'GOOD'
      ? fcdObservation(plot, '2026-08')
      : fcdObservation(plot, '2026-03')?.qa === 'GOOD'
        ? fcdObservation(plot, '2026-03')
        : null;
  }

  function fcdGreenPct(plot, month) {
    const obs = fcdObservation(plot, month);
    if (!obs || obs.qa !== 'GOOD' || !isFiniteNumber(obs.green_rai) || !plot.area_rai) return null;
    return obs.green_rai / plot.area_rai * 100;
  }

  function formatRai(value) {
    return isFiniteNumber(value)
      ? Number(value).toLocaleString('th-TH', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
      : '—';
  }

  function qaClass(qa) {
    return qa === 'GOOD' ? 'good' : qa === 'PARTIAL' ? 'partial' : qa === 'LOW_QA' ? 'low' : 'nodata';
  }

  loadData = async function pdd22LoadData() {
    const [catalogResponse, coverageResponse, fcdResponse, portfolioResponse] = await Promise.all([
      fetch(`data/pdd22/plots_catalog.json?v=${PDD22_VERSION}`, { cache: 'no-store' }),
      fetch(`data/pdd22_satellite/coverage_report.csv?v=${PDD22_VERSION}`, { cache: 'no-store' }),
      fetch(`data/pdd22_v3/plots_result.json?v=${PDD22_VERSION}`, { cache: 'no-store' }),
      fetch(`data/pdd22_v3/portfolio_summary.csv?v=${PDD22_VERSION}`, { cache: 'no-store' })
    ]);
    if (!catalogResponse.ok) throw new Error(`PDD22 catalog HTTP ${catalogResponse.status}`);
    if (!coverageResponse.ok) throw new Error(`PDD22 coverage HTTP ${coverageResponse.status}`);
    if (!fcdResponse.ok) throw new Error(`PDD22 FCD V3 HTTP ${fcdResponse.status}`);

    const catalog = await catalogResponse.json();
    const coverageRows = parseSimpleCsv(await coverageResponse.text());
    const fcdPlots = await fcdResponse.json();
    portfolioRows = portfolioResponse.ok ? parseSimpleCsv(await portfolioResponse.text()) : [];

    const coverageByCode = new Map();
    for (const row of coverageRows) {
      if (!coverageByCode.has(row.plot_code)) coverageByCode.set(row.plot_code, new Map());
      coverageByCode.get(row.plot_code).set(row.month, row);
    }
    const fcdByCode = new Map(fcdPlots.map(plot => [plot.code, plot]));

    plotsCatalog = catalog.map((plot, index) => ({
      ...plot,
      id: Number(plot.id) || index + 1,
      name: plot.name || plot.code,
      area_rai: Number(plot.area_rai)
    }));

    allPlotsData = plotsCatalog.map(plot => {
      const rows = coverageByCode.get(plot.code) || new Map();
      const fcd = fcdByCode.get(plot.code) || { observations: [] };
      const fcd_by_month = Object.fromEntries((fcd.observations || []).map(obs => [obs.month, {
        ...obs,
        green_rai: n(obs.green_rai),
        yellow_rai: n(obs.yellow_rai),
        red_rai: n(obs.red_rai),
        green_observed_rai: n(obs.green_observed_rai),
        yellow_observed_rai: n(obs.yellow_observed_rai),
        red_observed_rai: n(obs.red_observed_rai),
        coverage_pct: n(obs.coverage_pct)
      }]));

      const timeseries = MILESTONE_MONTHS.map(month => {
        const row = rows.get(month) || {};
        return {
          ...parseMonthKey(month),
          mean_ndvi_inside: n(row.mean_ndvi),
          median_ndvi_inside: n(row.median_ndvi),
          vegetation_coverage_proxy_pct: fcd_by_month[month]?.qa === 'GOOD' && fcd_by_month[month]?.green_rai != null
            ? fcd_by_month[month].green_rai / Number(plot.area_rai) * 100
            : null,
          scenes_used: Number(row.scene_count || 0),
          clear_pixel_pct: n(row.coverage_pct),
          status: row.qa || 'NO_DATA',
          source: 'PDD22 cleaned Sentinel-2 L2A',
          scene_ids: [],
          qa: row.qa || 'NO_DATA',
          analysis_mode: row.analysis_mode || 'no_data',
          median_ndre: n(row.median_ndre),
          median_mndwi: n(row.median_mndwi),
          median_mfi: n(row.median_mfi)
        };
      });

      const sep23 = timeseries.find(x => x.month === '2023-09');
      const aug26 = timeseries.find(x => x.month === '2026-08');
      const initial = sep23?.mean_ndvi_inside ?? null;
      const current = aug26?.mean_ndvi_inside ?? null;
      const gain = isFiniteNumber(initial) && isFiniteNumber(current) ? current - initial : null;
      const out = {
        ...plot,
        timeseries,
        fcd_by_month,
        initial_ndvi: initial,
        current_ndvi: current,
        gain_ndvi: gain,
        growth_pct: isFiniteNumber(initial) && initial !== 0 && isFiniteNumber(current) ? (current - initial) / Math.abs(initial) * 100 : null,
        current_vegetation_proxy_pct: null,
        data_quality: 'PDD22_CLEANED'
      };
      const latest = latestGoodFcd(out);
      out.current_vegetation_proxy_pct = latest && isFiniteNumber(latest.green_rai)
        ? latest.green_rai / out.area_rai * 100 : null;
      return out;
    });

    verifiedDatasetLoaded = true;
  };

  const baseInjectRuntimeStyles = injectRuntimeStyles;
  injectRuntimeStyles = function pdd22Styles() {
    baseInjectRuntimeStyles();
    const style = document.createElement('style');
    style.id = 'pdd22-production-styles';
    style.textContent = `
      .pdd-portfolio-banner{margin:0 0 14px;padding:13px 16px;border:1px solid rgba(56,189,248,.2);border-radius:12px;background:linear-gradient(135deg,rgba(14,116,144,.13),rgba(15,23,42,.78));display:flex;gap:18px;align-items:center;justify-content:space-between;flex-wrap:wrap}
      .pdd-portfolio-title{font-weight:800;color:#e2e8f0;font-size:.82rem}.pdd-portfolio-sub{color:#94a3b8;font-size:.65rem;margin-top:3px}
      .pdd-portfolio-values{display:flex;gap:8px;flex-wrap:wrap}.pdd-chip{border-radius:999px;padding:5px 9px;font-size:.65rem;font-weight:800;border:1px solid rgba(255,255,255,.08);background:#0f172a}
      .pdd-chip.green{color:#86efac}.pdd-chip.yellow{color:#fde047}.pdd-chip.red{color:#fca5a5}.pdd-chip.delta{color:#bae6fd}
      .fcd-summary-panel{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:0 0 14px}
      .fcd-card{border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px 12px;background:rgba(15,23,42,.72)}
      .fcd-card-label{font-size:.6rem;color:#94a3b8;font-weight:700}.fcd-card-value{font-size:1.15rem;font-weight:800;margin-top:3px}.fcd-card.green .fcd-card-value{color:#4ade80}.fcd-card.yellow .fcd-card-value{color:#facc15}.fcd-card.red .fcd-card-value{color:#fb7185}.fcd-card.qa .fcd-card-value{font-size:.8rem;color:#e2e8f0}
      .fcd-note{grid-column:1/-1;font-size:.61rem;color:#94a3b8;line-height:1.45;padding:0 2px}.fcd-note strong{color:#e2e8f0}
      .qa-pill-inline{display:inline-block;border-radius:999px;padding:2px 7px;font-size:.58rem;font-weight:800;margin-left:4px}.qa-pill-inline.good{background:rgba(34,197,94,.15);color:#86efac}.qa-pill-inline.partial{background:rgba(234,179,8,.14);color:#fde047}.qa-pill-inline.low,.qa-pill-inline.nodata{background:rgba(239,68,68,.14);color:#fca5a5}
      @media(max-width:850px){.fcd-summary-panel{grid-template-columns:1fr 1fr}}
    `;
    document.head.appendChild(style);
  };

  const baseUpdateStaticCopy = updateStaticCopy;
  updateStaticCopy = function pdd22Copy() {
    baseUpdateStaticCopy();
    document.title = 'PDD22 Mangrove Monitoring — Sentinel-2 + FCD';
    const title = document.querySelector('.brand-title');
    if (title) title.textContent = 'ระบบติดตาม PDD22 ป่าชายเลน — 22 แปลง';
    const subtitle = document.querySelector('.brand-subtitle');
    if (subtitle) subtitle.textContent = 'PDD participating area 6,775.53 ไร่ • Cleaned Sentinel-2 L2A • FCD V3 Green / Yellow / Red';
    const pills = document.querySelectorAll('.header-meta .meta-pill');
    if (pills[0]) pills[0].innerHTML = '<span class="pill-dot"></span> 22 PDD plots • 6,775.53 rai';
    if (pills[1]) pills[1].textContent = 'Participating boundary only';
    if (pills[2]) pills[2].textContent = 'Sentinel QA + FCD V3';

    const kpi4 = document.getElementById('kpi-plot-canopy-pct');
    const kpi4card = kpi4?.parentElement;
    if (kpi4card) {
      const label = kpi4card.querySelector('.kpi-label');
      const sub = kpi4card.querySelector('.kpi-sub');
      if (label) label.textContent = 'FCD Green ล่าสุด (QA GOOD)';
      if (sub) sub.textContent = 'PDD-anchored screening • ไม่ใช่ tCO₂e';
    }
    const chartTitle = document.getElementById('chart-plot-title');
    if (chartTitle) chartTitle.textContent = 'NDVI — cleaned Sentinel-2 exact-month observations';
    const chartSub = document.querySelector('.chart-box-subtitle');
    if (chartSub) chartSub.textContent = 'ใช้ขอบเขต PDD participating เท่านั้น • QA ตาม clear coverage • ไม่มี interpolation หรือ synthetic pixel';
    const badge = document.querySelector('.chart-badge-tag');
    if (badge) badge.textContent = 'PDD22 cleaned dataset';

    const hudGreen = document.getElementById('hud-in-cover')?.parentElement;
    if (hudGreen) hudGreen.firstChild.textContent = 'FCD Green: ';

    const bandGroup = document.querySelector('.band-btn-group');
    if (bandGroup && !bandGroup.querySelector('[data-layer="fcd"]')) {
      const button = document.createElement('button');
      button.className = 'band-btn';
      button.dataset.layer = 'fcd';
      button.textContent = 'FCD เขียว / เหลือง / แดง';
      button.onclick = () => setPlotMapLayer('fcd');
      bandGroup.appendChild(button);
    }

    const compareMode = document.getElementById('comp-mode-select');
    if (compareMode && !compareMode.querySelector('option[value="fcd"]')) {
      const opt = document.createElement('option');
      opt.value = 'fcd'; opt.textContent = 'FCD vs FCD'; compareMode.appendChild(opt);
    }

    injectPortfolioBanner();
    injectFcdPanel();
    const slider = document.getElementById('month-slider');
    if (slider) slider.disabled = false;
  };

  function injectPortfolioBanner() {
    if (document.getElementById('pdd-portfolio-banner')) return;
    const workspace = document.querySelector('.workspace-card');
    if (!workspace) return;
    const m24 = portfolioRows.find(r => r.month === '2024-03');
    const m26 = portfolioRows.find(r => r.month === '2026-03');
    const banner = document.createElement('div');
    banner.id = 'pdd-portfolio-banner';
    banner.className = 'pdd-portfolio-banner';
    if (m26) {
      const dg = n(m26.green_rai) - n(m24?.green_rai);
      banner.innerHTML = `<div><div class="pdd-portfolio-title">ภาพรวม FCD มีนาคม 2569 — ครบ 22 แปลง / 6,775.53 ไร่</div><div class="pdd-portfolio-sub">เทียบแบบ same-season กับมีนาคม 2567 • ผล screening ไม่ใช่การคำนวณคาร์บอนเครดิต</div></div><div class="pdd-portfolio-values"><span class="pdd-chip green">เขียว ${formatRai(n(m26.green_rai))} ไร่</span><span class="pdd-chip yellow">เหลือง ${formatRai(n(m26.yellow_rai))} ไร่</span><span class="pdd-chip red">แดง ${formatRai(n(m26.red_rai))} ไร่</span><span class="pdd-chip delta">Δเขียว ${dg >= 0 ? '+' : ''}${formatRai(dg)} ไร่</span></div>`;
    } else {
      banner.textContent = 'กำลังโหลดผล FCD V3';
    }
    workspace.parentNode.insertBefore(banner, workspace);
  }

  function injectFcdPanel() {
    if (document.getElementById('fcd-summary-panel')) return;
    const chart = document.querySelector('#panel-detail .chart-box');
    if (!chart) return;
    const panel = document.createElement('div');
    panel.id = 'fcd-summary-panel';
    panel.className = 'fcd-summary-panel';
    panel.innerHTML = `
      <div class="fcd-card green"><div class="fcd-card-label">FCD เขียว</div><div class="fcd-card-value" id="fcd-green-value">—</div></div>
      <div class="fcd-card yellow"><div class="fcd-card-label">FCD เหลือง</div><div class="fcd-card-value" id="fcd-yellow-value">—</div></div>
      <div class="fcd-card red"><div class="fcd-card-label">FCD แดง</div><div class="fcd-card-value" id="fcd-red-value">—</div></div>
      <div class="fcd-card qa"><div class="fcd-card-label">QA / Coverage</div><div class="fcd-card-value" id="fcd-qa-value">—</div></div>
      <div class="fcd-note" id="fcd-note">FCD มีสำหรับ มี.ค. 2567, มี.ค. 2568, มี.ค. 2569 และ ส.ค. 2569</div>`;
    chart.insertAdjacentElement('afterend', panel);
  }

  function updateFcdPanel() {
    if (!activePlot) return;
    const month = activePlot.timeseries?.[currentMonthIndex]?.month;
    const obs = fcdObservation(activePlot, month);
    const greenEl = document.getElementById('fcd-green-value');
    const yellowEl = document.getElementById('fcd-yellow-value');
    const redEl = document.getElementById('fcd-red-value');
    const qaEl = document.getElementById('fcd-qa-value');
    const note = document.getElementById('fcd-note');
    const hud = document.getElementById('hud-in-cover');
    if (!greenEl || !obs) {
      if (greenEl) greenEl.textContent = '—';
      if (yellowEl) yellowEl.textContent = '—';
      if (redEl) redEl.textContent = '—';
      if (qaEl) qaEl.textContent = FCD_MONTHS.has(month) ? 'ไม่มีผล' : 'นอกช่วง FCD';
      if (note) note.innerHTML = `<strong>${activePlot.code}</strong> • เดือน ${month || '—'} ไม่มี FCD V3; เลือก มี.ค. 2567/68/69 หรือ ส.ค. 2569`;
      if (hud) hud.textContent = '—';
      return;
    }
    const equivalent = obs.qa === 'GOOD' && isFiniteNumber(obs.green_rai);
    const g = equivalent ? obs.green_rai : obs.green_observed_rai;
    const y = equivalent ? obs.yellow_rai : obs.yellow_observed_rai;
    const r = equivalent ? obs.red_rai : obs.red_observed_rai;
    greenEl.textContent = `${formatRai(g)} ไร่`;
    yellowEl.textContent = `${formatRai(y)} ไร่`;
    redEl.textContent = `${formatRai(r)} ไร่`;
    qaEl.innerHTML = `${obs.qa} <span class="qa-pill-inline ${qaClass(obs.qa)}">${isFiniteNumber(obs.coverage_pct) ? obs.coverage_pct.toFixed(1) : '—'}%</span>`;
    if (note) note.innerHTML = equivalent
      ? `<strong>${activePlot.code} • ${month}</strong> — equivalent class area จาก QA GOOD; Green/Yellow/Red รวมบน PDD participating area (แยก water/bare ตาม model)`
      : `<strong>${activePlot.code} • ${month}</strong> — QA ${obs.qa}; ตัวเลขข้างต้นเป็น observed-only และ <strong>ไม่ extrapolate เต็มแปลง</strong>`;
    if (hud) hud.textContent = equivalent ? `${(obs.green_rai / activePlot.area_rai * 100).toFixed(1)}%` : 'QA<95%';
  }

  renderSidebarList = function pdd22Sidebar(plots) {
    const container = document.getElementById('plot-list-container');
    document.getElementById('sidebar-count-display').textContent = `แสดง ${plots.length} จาก ${allPlotsData.length} PDD plots`;
    container.innerHTML = '';
    plots.forEach(plot => {
      const march24 = fcdObservation(plot, '2024-03');
      const march26 = fcdObservation(plot, '2026-03');
      const dg = march24?.qa === 'GOOD' && march26?.qa === 'GOOD' ? march26.green_rai - march24.green_rai : null;
      const card = document.createElement('div');
      card.className = `plot-card-item ${activePlot?.id === plot.id ? 'active' : ''}`;
      card.id = `sidebar-card-${plot.id}`;
      card.onclick = () => selectPlot(plot.id);
      card.innerHTML = `<div class="p-card-header"><span class="p-card-title">${escapeHtml(plot.code)}</span><span class="p-prov-tag">${escapeHtml(plot.province)}</span></div><div class="p-card-body"><span>พื้นที่ <strong>${Number(plot.area_rai).toFixed(2)} ไร่</strong></span><span>${isFiniteNumber(dg) ? `Δเขียว 67→69 <strong>${dg >= 0 ? '+' : ''}${dg.toFixed(1)} ไร่</strong>` : 'FCD comparison —'}</span></div>`;
      container.appendChild(card);
    });
  };

  initLeafletThailandMap = function pdd22ThailandMap() {
    leafletMap = L.map('thailand-map').setView([9.2, 100.0], 6);
    L.tileLayer(ESRI_WORLD_IMAGERY, { maxZoom: 19, attribution: 'Tiles &copy; Esri' }).addTo(leafletMap);
    const features = allPlotsData.map(plot => ({ type: 'Feature', properties: { id: plot.id, code: plot.code, province: plot.province, area_rai: plot.area_rai }, geometry: plot.geometry }));
    thailandGeojsonLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
      style: feature => {
        const plot = allPlotsData.find(p => p.id === feature.properties.id);
        const a = fcdObservation(plot, '2026-03');
        const color = a?.qa === 'GOOD' && a.red_rai > a.green_rai ? '#fb7185' : '#22c55e';
        return { color, weight: 2, opacity: .95, fillColor: color, fillOpacity: .08 };
      },
      onEachFeature: (feature, layer) => {
        const plot = allPlotsData.find(p => p.id === feature.properties.id);
        const a = fcdObservation(plot, '2026-03');
        const fcdText = a?.qa === 'GOOD' ? `เขียว ${formatRai(a.green_rai)} • เหลือง ${formatRai(a.yellow_rai)} • แดง ${formatRai(a.red_rai)} ไร่` : 'FCD QA ไม่เพียงพอ';
        layer.bindPopup(`<div class="popup-title">${escapeHtml(plot.code)}</div><div class="popup-meta">${escapeHtml(plot.province)} • ${Number(plot.area_rai).toFixed(2)} ไร่<br>มี.ค. 2569: ${fcdText}</div><button class="popup-btn" onclick="selectPlot(${plot.id}); switchWorkspaceTab('detail');">ดูแปลงนี้</button>`);
        layer.on('click', () => selectPlot(plot.id));
      }
    }).addTo(leafletMap);
    const bounds = thailandGeojsonLayer.getBounds();
    if (bounds.isValid()) leafletMap.fitBounds(bounds, { padding: [20, 20] });
  };

  setPlotMapLayer = function pdd22Layer(layerKey) {
    currentPlotLayerKey = layerKey;
    document.querySelectorAll('.band-btn-group .band-btn').forEach(button => button.classList.toggle('active', button.dataset.layer === layerKey));
    sentinelSwapToken++;
    if (layerKey === 'esri') {
      if (pendingSentinelOverlay && plotSatelliteMap?.hasLayer(pendingSentinelOverlay)) plotSatelliteMap.removeLayer(pendingSentinelOverlay);
      pendingSentinelOverlay = null;
      if (currentSentinelOverlay && plotSatelliteMap?.hasLayer(currentSentinelOverlay)) plotSatelliteMap.removeLayer(currentSentinelOverlay);
      currentSentinelOverlay = null;
      return;
    }
    updateGeeOverlay();
  };

  updateGeeOverlay = async function pdd22Overlay() {
    if (!activePlot || !plotSatelliteMap || currentPlotLayerKey === 'esri') return;
    const item = activePlot.timeseries[currentMonthIndex];
    if (!item) return;
    let url;
    if (currentPlotLayerKey === 'fcd') {
      if (!FCD_MONTHS.has(item.month)) {
        if (currentSentinelOverlay && plotSatelliteMap.hasLayer(currentSentinelOverlay)) plotSatelliteMap.removeLayer(currentSentinelOverlay);
        currentSentinelOverlay = null;
        return;
      }
      url = `data/pdd22_v3/maps/${activePlot.code}/fcd_${item.month}.png?v=${PDD22_VERSION}`;
    } else {
      const prefix = currentPlotLayerKey === 'gee_ndvi' ? 'ndvi' : 'rgb';
      url = `data/pdd22_satellite/plots/${activePlot.code}/${item.month}/${prefix}.png?v=${PDD22_VERSION}`;
    }
    const token = ++sentinelSwapToken;
    try {
      await preloadImage(url);
      if (token !== sentinelSwapToken || !activePlot) return;
      const next = L.imageOverlay(url, imageBoundsForPlot(activePlot), { opacity: .92, interactive: false, className: 'sentinel-overlay' });
      next.addTo(plotSatelliteMap);
      if (currentSentinelOverlay && plotSatelliteMap.hasLayer(currentSentinelOverlay)) plotSatelliteMap.removeLayer(currentSentinelOverlay);
      currentSentinelOverlay = next;
      pendingSentinelOverlay = null;
      if (plotBoundaryLayer && document.getElementById('toggle-boundary-check')?.checked !== false) plotBoundaryLayer.bringToFront();
    } catch (error) {
      console.warn('PDD22 overlay unavailable', url, error);
    }
  };

  const baseSetMonthIndex = setMonthIndex;
  setMonthIndex = function pdd22Month(index) {
    baseSetMonthIndex(index);
    updateFcdPanel();
    const tag = document.querySelector('.stage-hud.top-right .hud-tag');
    const sub = document.querySelector('.stage-hud.top-right .hud-sub');
    if (tag) tag.textContent = currentPlotLayerKey === 'fcd' ? 'FCD V3 screening' : 'Cleaned Sentinel-2';
    if (sub) sub.textContent = currentPlotLayerKey === 'fcd' ? 'Green / Yellow / Red • PDD participating boundary' : 'SCL QA • exact-month • no interpolation';
  };

  const baseSelectPlot = selectPlot;
  selectPlot = function pdd22Select(id) {
    baseSelectPlot(id);
    updateFcdPanel();
    const latest = latestGoodFcd(activePlot);
    const kpi = document.getElementById('kpi-plot-canopy-pct');
    if (kpi) kpi.textContent = latest && isFiniteNumber(latest.green_rai) ? `${(latest.green_rai / activePlot.area_rai * 100).toFixed(1)}%` : '—';
  };

  initTable = function pdd22Table(plots) {
    const table = document.getElementById('plots-data-table');
    const tbody = document.getElementById('table-body');
    document.getElementById('table-count-label').textContent = `PDD participating plots ${plots.length} แปลง • 6,775.53 ไร่`;
    table.querySelector('thead').innerHTML = `<tr><th>รหัสแปลง</th><th>จังหวัด</th><th>พื้นที่ (ไร่)</th><th>เขียว มี.ค.69</th><th>เหลือง มี.ค.69</th><th>แดง มี.ค.69</th><th>Δเขียว มี.ค.67→69</th><th>ส.ค.69 QA</th><th>การกระทำ</th></tr>`;
    tbody.innerHTML = '';
    plots.forEach(plot => {
      const a24 = fcdObservation(plot, '2024-03');
      const a26 = fcdObservation(plot, '2026-03');
      const aug = fcdObservation(plot, '2026-08');
      const dg = a24?.qa === 'GOOD' && a26?.qa === 'GOOD' ? a26.green_rai - a24.green_rai : null;
      const row = document.createElement('tr');
      row.innerHTML = `<td><strong>${escapeHtml(plot.code)}</strong></td><td>${escapeHtml(plot.province)}</td><td>${Number(plot.area_rai).toFixed(2)}</td><td>${formatRai(a26?.green_rai)}</td><td>${formatRai(a26?.yellow_rai)}</td><td>${formatRai(a26?.red_rai)}</td><td><strong>${isFiniteNumber(dg) ? `${dg >= 0 ? '+' : ''}${dg.toFixed(2)}` : '—'}</strong></td><td><span class="qa-pill-inline ${qaClass(aug?.qa)}">${aug?.qa || '—'}</span></td><td><button class="btn-table-view">ดูรายละเอียด</button></td>`;
      row.querySelector('button').onclick = () => { selectPlot(plot.id); switchWorkspaceTab('detail'); };
      tbody.appendChild(row);
    });
  };

  exportPlotsCSV = function pdd22Csv() {
    const header = ['Plot Code','Province','PDD Area Rai','Green Mar 2024','Yellow Mar 2024','Red Mar 2024','Green Mar 2026','Yellow Mar 2026','Red Mar 2026','Delta Green Mar24-Mar26','Aug 2026 QA'];
    const rows = allPlotsData.map(plot => {
      const a = fcdObservation(plot,'2024-03'); const b = fcdObservation(plot,'2026-03'); const aug = fcdObservation(plot,'2026-08');
      const dg = a?.qa === 'GOOD' && b?.qa === 'GOOD' ? b.green_rai - a.green_rai : '';
      return [plot.code, plot.province, plot.area_rai, a?.green_rai ?? '', a?.yellow_rai ?? '', a?.red_rai ?? '', b?.green_rai ?? '', b?.yellow_rai ?? '', b?.red_rai ?? '', dg, aug?.qa ?? ''];
    });
    const csv = '\uFEFF' + [header.join(','), ...rows.map(row => row.join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'pdd22_fcd_v3.csv'; a.click(); URL.revokeObjectURL(url);
  };

  const baseInitCompareSelectors = initCompareSelectors;
  initCompareSelectors = function pdd22CompareSelectors(plot) {
    baseInitCompareSelectors(plot);
    const left = document.getElementById('comp-left-select');
    const right = document.getElementById('comp-right-select');
    if (left) left.value = '2';
    if (right) right.value = '10';
  };

  updateCompareView = function pdd22Compare() {
    if (!activePlot) return;
    ensureCompareMaps();
    let li = Math.max(0, Math.min(11, parseInt(document.getElementById('comp-left-select').value || '2', 10)));
    let ri = Math.max(0, Math.min(11, parseInt(document.getElementById('comp-right-select').value || '10', 10)));
    const mode = document.getElementById('comp-mode-select')?.value || 'rgb';
    if (mode === 'fcd') {
      if (!FCD_MONTHS.has(activePlot.timeseries[li].month)) li = 2;
      if (!FCD_MONTHS.has(activePlot.timeseries[ri].month)) ri = 10;
      document.getElementById('comp-left-select').value = String(li);
      document.getElementById('comp-right-select').value = String(ri);
    }
    const leftItem = activePlot.timeseries[li], rightItem = activePlot.timeseries[ri];
    let leftUrl, rightUrl, leftLabel, rightLabel;
    if (mode === 'fcd') {
      leftUrl = `data/pdd22_v3/maps/${activePlot.code}/fcd_${leftItem.month}.png?v=${PDD22_VERSION}`;
      rightUrl = `data/pdd22_v3/maps/${activePlot.code}/fcd_${rightItem.month}.png?v=${PDD22_VERSION}`;
      leftLabel = `${leftItem.month} • FCD`; rightLabel = `${rightItem.month} • FCD`;
    } else {
      let lp = 'rgb', rp = 'rgb';
      if (mode === 'ndvi') lp = rp = 'ndvi';
      if (mode === 'rgb_vs_ndvi') rp = 'ndvi';
      leftUrl = `data/pdd22_satellite/plots/${activePlot.code}/${leftItem.month}/${lp}.png?v=${PDD22_VERSION}`;
      rightUrl = `data/pdd22_satellite/plots/${activePlot.code}/${rightItem.month}/${rp}.png?v=${PDD22_VERSION}`;
      leftLabel = `${leftItem.month} • ${lp.toUpperCase()}`; rightLabel = `${rightItem.month} • ${rp.toUpperCase()}`;
    }
    document.getElementById('comp-label-before').textContent = leftLabel;
    document.getElementById('comp-label-after').textContent = rightLabel;
    compareLeftOverlay = replaceCompareLayer(compareLeftMap, compareLeftOverlay, leftUrl, activePlot);
    compareRightOverlay = replaceCompareLayer(compareRightMap, compareRightOverlay, rightUrl, activePlot);
    const show = document.getElementById('comp-boundary-toggle')?.checked !== false;
    compareLeftBoundary = replaceCompareBoundary(compareLeftMap, compareLeftBoundary, activePlot, show);
    compareRightBoundary = replaceCompareBoundary(compareRightMap, compareRightBoundary, activePlot, show);
    const bounds = L.geoJSON({ type:'Feature', properties:{}, geometry:activePlot.geometry }).getBounds();
    if (bounds.isValid()) { const opts={padding:[34,34],maxZoom:17,animate:false}; compareLeftMap.fitBounds(bounds,opts); compareRightMap.fitBounds(bounds,opts); }
    const stat = document.getElementById('comp-in-stat-text'), pill = document.getElementById('comp-gain-pill');
    if (mode === 'fcd') {
      const a=fcdObservation(activePlot,leftItem.month), b=fcdObservation(activePlot,rightItem.month);
      if (a?.qa==='GOOD' && b?.qa==='GOOD') { const dg=b.green_rai-a.green_rai; stat.innerHTML=`FCD Green: <strong>${formatRai(a.green_rai)}</strong> ➜ <strong>${formatRai(b.green_rai)}</strong> ไร่`; pill.textContent=`Δ ${dg>=0?'+':''}${dg.toFixed(1)} ไร่`; }
      else { stat.textContent='FCD comparison ต้องใช้ QA GOOD เพื่อเทียบพื้นที่เต็มแปลง'; pill.textContent='QA guardrail'; }
    } else {
      const a=leftItem.mean_ndvi_inside,b=rightItem.mean_ndvi_inside;
      if(isFiniteNumber(a)&&isFiniteNumber(b)){const d=b-a;stat.innerHTML=`Mean NDVI: <strong>${a.toFixed(3)}</strong> ➜ <strong>${b.toFixed(3)}</strong>`;pill.textContent=`${d>=0?'+':''}${d.toFixed(3)}`;} else {stat.textContent='ไม่มี NDVI ที่ผ่าน QA สำหรับช่วงที่เลือก';pill.textContent='No metric';}
    }
  };
})();
