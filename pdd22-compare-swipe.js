// PDD22 Before/After swipe comparison — restores the original single-map draggable slider.
(() => {
  const VERSION = '20260826-1425';
  const FCD_MONTHS = new Set(['2024-03', '2025-03', '2026-03', '2026-08']);

  let swipeMap = null;
  let baseLayer = null;
  let beforeOverlay = null;
  let afterOverlay = null;
  let boundaryLayer = null;
  let swipePercent = 50;
  let requestToken = 0;
  let eventsBound = false;

  const fcdObs = (plot, month) => plot?.fcd_by_month?.[month] || null;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const fmtRai = value => finite(value)
    ? Number(value).toLocaleString('th-TH', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
    : '—';

  function injectStyles() {
    if (document.getElementById('pdd22-swipe-styles')) return;
    const style = document.createElement('style');
    style.id = 'pdd22-swipe-styles';
    style.textContent = `
      .compare-stage {
        display:block !important;
        position:relative !important;
        width:100% !important;
        height:640px !important;
        min-height:440px !important;
        overflow:hidden !important;
        cursor:ew-resize !important;
        background:#0b1120 !important;
        touch-action:none;
        user-select:none;
      }
      .pdd22-swipe-map { position:absolute; inset:0; z-index:1; }
      .pdd22-swipe-label {
        position:absolute; top:14px; z-index:650;
        background:rgba(15,23,42,.92); color:#fff;
        border:1px solid rgba(255,255,255,.16);
        border-radius:8px; padding:7px 11px;
        font-size:.78rem; font-weight:700; pointer-events:none;
        box-shadow:0 2px 10px rgba(0,0,0,.28);
      }
      .pdd22-swipe-label.before { left:14px; }
      .pdd22-swipe-label.after { right:14px; }
      .pdd22-swipe-divider {
        position:absolute; top:0; bottom:0; left:50%;
        width:3px; transform:translateX(-1.5px);
        z-index:700; background:#fff; pointer-events:none;
        box-shadow:0 0 0 1px rgba(15,23,42,.3),0 0 14px rgba(0,0,0,.55);
      }
      .pdd22-swipe-handle {
        position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
        width:50px; height:50px; border-radius:50%;
        display:flex; align-items:center; justify-content:center;
        background:#fff; color:#0f172a; font-size:20px; font-weight:900;
        box-shadow:0 4px 16px rgba(0,0,0,.48);
      }
      .pdd22-swipe-caption {
        position:absolute; left:50%; bottom:14px; transform:translateX(-50%);
        z-index:650; pointer-events:none;
        background:rgba(15,23,42,.9); color:#cbd5e1;
        border:1px solid rgba(255,255,255,.12); border-radius:999px;
        padding:6px 11px; font-size:.7rem; white-space:nowrap;
      }
      @media(max-width:800px) {
        .compare-stage { height:500px !important; min-height:380px !important; }
        .pdd22-swipe-label { font-size:.68rem; padding:6px 8px; }
        .pdd22-swipe-handle { width:42px; height:42px; }
      }
    `;
    document.head.appendChild(style);
  }

  function setPosition(percent) {
    swipePercent = Math.max(0, Math.min(100, Number(percent) || 0));
    const divider = document.getElementById('pdd22-swipe-divider');
    if (divider) divider.style.left = `${swipePercent}%`;

    const beforeElement = beforeOverlay?.getElement?.();
    const stage = document.getElementById('compare-container');
    if (!beforeElement || !stage) return;

    const stageRect = stage.getBoundingClientRect();
    const imageRect = beforeElement.getBoundingClientRect();
    if (!imageRect.width) return;
    const dividerX = stageRect.left + stageRect.width * swipePercent / 100;
    const relative = Math.max(0, Math.min(100, ((dividerX - imageRect.left) / imageRect.width) * 100));
    const clip = `polygon(0 0, ${relative}% 0, ${relative}% 100%, 0 100%)`;
    beforeElement.style.clipPath = clip;
    beforeElement.style.webkitClipPath = clip;
  }

  function bindEvents() {
    if (eventsBound) return;
    const stage = document.getElementById('compare-container');
    if (!stage) return;
    eventsBound = true;
    let dragging = false;

    const update = event => {
      if (!dragging) return;
      if (event.cancelable) event.preventDefault();
      const rect = stage.getBoundingClientRect();
      setPosition((event.clientX - rect.left) / rect.width * 100);
    };

    stage.addEventListener('pointerdown', event => {
      if (event.target.closest('.leaflet-control')) return;
      dragging = true;
      stage.setPointerCapture?.(event.pointerId);
      update(event);
    });
    stage.addEventListener('pointermove', update);
    stage.addEventListener('pointerup', event => {
      dragging = false;
      if (stage.hasPointerCapture?.(event.pointerId)) stage.releasePointerCapture(event.pointerId);
    });
    stage.addEventListener('pointercancel', () => { dragging = false; });
    window.addEventListener('resize', () => requestAnimationFrame(() => setPosition(swipePercent)));
  }

  window.ensureCompareMaps = function pdd22EnsureSwipeMap() {
    injectStyles();
    if (swipeMap) return;
    const container = document.getElementById('compare-container');
    if (!container) return;

    container.innerHTML = `
      <div id="pdd22-swipe-map" class="pdd22-swipe-map"></div>
      <div id="comp-label-before" class="pdd22-swipe-label before">Before</div>
      <div id="comp-label-after" class="pdd22-swipe-label after">After</div>
      <div id="pdd22-swipe-divider" class="pdd22-swipe-divider"><div class="pdd22-swipe-handle">↔</div></div>
      <div class="pdd22-swipe-caption">ลากเส้นกลางซ้าย–ขวาเพื่อเปรียบเทียบ</div>
    `;

    swipeMap = L.map('pdd22-swipe-map', {
      zoomControl:true,
      attributionControl:true,
      dragging:false,
      scrollWheelZoom:false,
      doubleClickZoom:false,
      boxZoom:false,
      keyboard:false
    }).setView([12.75,101.80],15);

    baseLayer = L.tileLayer(ESRI_WORLD_IMAGERY, { maxZoom:19, attribution:'Tiles &copy; Esri' }).addTo(swipeMap);
    swipeMap.createPane('pdd22AfterPane'); swipeMap.getPane('pdd22AfterPane').style.zIndex = 410;
    swipeMap.createPane('pdd22BeforePane'); swipeMap.getPane('pdd22BeforePane').style.zIndex = 420;
    swipeMap.createPane('pdd22BoundaryPane'); swipeMap.getPane('pdd22BoundaryPane').style.zIndex = 430;
    swipeMap.on('zoom move resize', () => requestAnimationFrame(() => setPosition(swipePercent)));
    bindEvents();
  };

  function replaceBoundary(plot, show) {
    if (boundaryLayer && swipeMap?.hasLayer(boundaryLayer)) swipeMap.removeLayer(boundaryLayer);
    boundaryLayer = L.geoJSON({ type:'Feature', properties:{}, geometry:plot.geometry }, {
      pane:'pdd22BoundaryPane',
      style:{ color:'#34d399', weight:2.5, opacity:1, fillOpacity:0 }
    });
    if (show) boundaryLayer.addTo(swipeMap);
  }

  function imageSpec(plot, item, mode, side) {
    if (mode === 'fcd') {
      return {
        url:`data/pdd22_v3/maps/${plot.code}/fcd_${item.month}.png?v=${VERSION}`,
        label:`${item.month} • FCD`
      };
    }
    let prefix = 'rgb';
    if (mode === 'ndvi') prefix = 'ndvi';
    if (mode === 'rgb_vs_ndvi' && side === 'after') prefix = 'ndvi';
    return {
      url:`data/pdd22_satellite/plots/${plot.code}/${item.month}/${prefix}.png?v=${VERSION}`,
      label:`${item.month} • ${prefix.toUpperCase()}`
    };
  }

  window.updateCompareView = async function pdd22SwipeCompare() {
    if (!activePlot) return;
    window.ensureCompareMaps();
    if (!swipeMap) return;

    let li = Math.max(0, Math.min(11, parseInt(document.getElementById('comp-left-select')?.value || '2', 10)));
    let ri = Math.max(0, Math.min(11, parseInt(document.getElementById('comp-right-select')?.value || '10', 10)));
    const mode = document.getElementById('comp-mode-select')?.value || 'rgb';

    if (mode === 'fcd') {
      if (!FCD_MONTHS.has(activePlot.timeseries[li]?.month)) li = 2;
      if (!FCD_MONTHS.has(activePlot.timeseries[ri]?.month)) ri = 10;
      document.getElementById('comp-left-select').value = String(li);
      document.getElementById('comp-right-select').value = String(ri);
    }

    const beforeItem = activePlot.timeseries[li];
    const afterItem = activePlot.timeseries[ri];
    if (!beforeItem || !afterItem) return;

    const before = imageSpec(activePlot, beforeItem, mode, 'before');
    const after = imageSpec(activePlot, afterItem, mode, 'after');
    const token = ++requestToken;

    try {
      await Promise.all([preloadImage(before.url), preloadImage(after.url)]);
    } catch (error) {
      if (token === requestToken) console.warn('PDD22 swipe image unavailable', error);
      return;
    }
    if (token !== requestToken) return;

    const oldBefore = beforeOverlay;
    const oldAfter = afterOverlay;
    afterOverlay = L.imageOverlay(after.url, imageBoundsForPlot(activePlot), {
      opacity:.94, interactive:false, pane:'pdd22AfterPane', className:'sentinel-overlay'
    }).addTo(swipeMap);
    beforeOverlay = L.imageOverlay(before.url, imageBoundsForPlot(activePlot), {
      opacity:.94, interactive:false, pane:'pdd22BeforePane', className:'sentinel-overlay'
    }).addTo(swipeMap);

    const finish = () => {
      if (token !== requestToken) return;
      setPosition(swipePercent);
      if (oldBefore && swipeMap.hasLayer(oldBefore)) swipeMap.removeLayer(oldBefore);
      if (oldAfter && swipeMap.hasLayer(oldAfter)) swipeMap.removeLayer(oldAfter);
      boundaryLayer?.bringToFront?.();
    };
    beforeOverlay.once('load', () => requestAnimationFrame(finish));

    const beforeLabel = document.getElementById('comp-label-before');
    const afterLabel = document.getElementById('comp-label-after');
    if (beforeLabel) beforeLabel.textContent = before.label;
    if (afterLabel) afterLabel.textContent = after.label;

    replaceBoundary(activePlot, document.getElementById('comp-boundary-toggle')?.checked !== false);
    const bounds = boundaryLayer.getBounds();
    if (bounds.isValid()) swipeMap.fitBounds(bounds, { padding:[42,42], maxZoom:17, animate:false });
    comparePlotId = activePlot.id;

    requestAnimationFrame(() => {
      swipeMap.invalidateSize();
      setPosition(50);
    });

    const stat = document.getElementById('comp-in-stat-text');
    const pill = document.getElementById('comp-gain-pill');
    if (mode === 'fcd') {
      const a = fcdObs(activePlot, beforeItem.month);
      const b = fcdObs(activePlot, afterItem.month);
      if (a?.qa === 'GOOD' && b?.qa === 'GOOD' && finite(a.green_rai) && finite(b.green_rai)) {
        const delta = b.green_rai - a.green_rai;
        if (stat) stat.innerHTML = `FCD Green: <strong>${fmtRai(a.green_rai)}</strong> ➜ <strong>${fmtRai(b.green_rai)}</strong> ไร่`;
        if (pill) pill.textContent = `Δ ${delta >= 0 ? '+' : ''}${delta.toFixed(1)} ไร่`;
      } else {
        if (stat) stat.textContent = 'FCD พื้นที่เต็มแปลงเปรียบเทียบได้เมื่อ QA = GOOD ทั้งสองช่วง';
        if (pill) pill.textContent = 'QA guardrail';
      }
    } else {
      const a = beforeItem.mean_ndvi_inside;
      const b = afterItem.mean_ndvi_inside;
      if (finite(a) && finite(b)) {
        const delta = b - a;
        if (stat) stat.innerHTML = `Mean NDVI: <strong>${a.toFixed(3)}</strong> ➜ <strong>${b.toFixed(3)}</strong>`;
        if (pill) pill.textContent = `${delta >= 0 ? '+' : ''}${delta.toFixed(3)}`;
      } else {
        if (stat) stat.textContent = 'ไม่มี NDVI ที่ผ่าน QA สำหรับช่วงที่เลือก';
        if (pill) pill.textContent = 'No metric';
      }
    }
  };

  window.toggleCompareBoundary = function pdd22SwipeBoundary(show) {
    if (!swipeMap || !boundaryLayer) return;
    if (show && !swipeMap.hasLayer(boundaryLayer)) { boundaryLayer.addTo(swipeMap); boundaryLayer.bringToFront?.(); }
    if (!show && swipeMap.hasLayer(boundaryLayer)) swipeMap.removeLayer(boundaryLayer);
  };

  document.addEventListener('DOMContentLoaded', () => {
    injectStyles();
    const hint = document.querySelector('.compare-hint');
    if (hint) hint.textContent = 'ลากเส้นแบ่งกลางไปทางซ้ายหรือขวาเพื่อเปรียบเทียบ Before / After บนแผนที่เดียวกัน';
  });
})();
