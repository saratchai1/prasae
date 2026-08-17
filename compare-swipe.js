// Stable Before/After swipe comparison for Prasae.
// This module only replaces compare-view behavior. It does not touch plot selection.

let compareSwipeMap = null;
let compareSwipeBaseLayer = null;
let compareSwipeBeforeOverlay = null;
let compareSwipeAfterOverlay = null;
let compareSwipeBoundaryLayer = null;
let compareSwipePercent = 50;
let compareSwipeRequestToken = 0;
let compareSwipeEventsReady = false;

function injectCompareSwipeStyles() {
  if (document.getElementById('compare-swipe-styles')) return;
  const style = document.createElement('style');
  style.id = 'compare-swipe-styles';
  style.textContent = `
    .compare-stage {
      display:block !important;
      position:relative !important;
      width:100% !important;
      height:560px !important;
      min-height:420px !important;
      overflow:hidden !important;
      cursor:ew-resize !important;
      background:#0b1120 !important;
      touch-action:none;
      user-select:none;
    }
    .compare-swipe-map { position:absolute; inset:0; z-index:1; }
    .compare-swipe-label {
      position:absolute; top:14px; z-index:650;
      background:rgba(15,23,42,.92); color:#fff;
      border:1px solid rgba(255,255,255,.16);
      border-radius:8px; padding:7px 11px;
      font-size:.78rem; font-weight:700; pointer-events:none;
      box-shadow:0 2px 10px rgba(0,0,0,.28);
    }
    .compare-swipe-label.before { left:14px; }
    .compare-swipe-label.after { right:14px; }
    .compare-swipe-divider {
      position:absolute; top:0; bottom:0; left:50%;
      width:3px; transform:translateX(-1.5px);
      z-index:700; background:#fff; pointer-events:none;
      box-shadow:0 0 0 1px rgba(15,23,42,.25), 0 0 12px rgba(0,0,0,.45);
    }
    .compare-swipe-handle {
      position:absolute; top:50%; left:50%;
      transform:translate(-50%,-50%);
      width:46px; height:46px; border-radius:50%;
      display:flex; align-items:center; justify-content:center;
      background:#fff; color:#0f172a; font-size:20px; font-weight:800;
      box-shadow:0 4px 14px rgba(0,0,0,.45);
    }
    .compare-swipe-caption {
      position:absolute; left:50%; bottom:14px; transform:translateX(-50%);
      z-index:650; pointer-events:none;
      background:rgba(15,23,42,.88); color:#cbd5e1;
      border:1px solid rgba(255,255,255,.12); border-radius:999px;
      padding:5px 10px; font-size:.72rem; white-space:nowrap;
    }
    @media (max-width:700px) {
      .compare-stage { height:440px !important; min-height:360px !important; }
      .compare-swipe-label { font-size:.7rem; padding:6px 8px; }
      .compare-swipe-handle { width:40px; height:40px; }
    }
  `;
  document.head.appendChild(style);
}

function compareSwipeImageUrl(plot, prefix, item) {
  return `data/plots/${plot.id}/${prefix}_${item.month}.png?v=${ASSET_VERSION}`;
}

function setCompareSwipePosition(percent) {
  compareSwipePercent = Math.max(0, Math.min(100, Number(percent) || 0));

  const divider = document.getElementById('compare-swipe-divider');
  if (divider) divider.style.left = `${compareSwipePercent}%`;

  const beforeElement = compareSwipeBeforeOverlay?.getElement?.();
  const stage = document.getElementById('compare-container');
  if (!beforeElement || !stage) return;

  // Clip at the divider's screen position, not at a percentage of the raster.
  // This keeps the swipe line geographically correct even when the image has map padding.
  const stageRect = stage.getBoundingClientRect();
  const imageRect = beforeElement.getBoundingClientRect();
  if (!imageRect.width) return;

  const dividerX = stageRect.left + (stageRect.width * compareSwipePercent / 100);
  const relativePercent = Math.max(0, Math.min(100,
    ((dividerX - imageRect.left) / imageRect.width) * 100
  ));

  beforeElement.style.clipPath = `polygon(0 0, ${relativePercent}% 0, ${relativePercent}% 100%, 0 100%)`;
  beforeElement.style.webkitClipPath = beforeElement.style.clipPath;
}

function bindCompareSwipeEvents() {
  if (compareSwipeEventsReady) return;
  const stage = document.getElementById('compare-container');
  if (!stage) return;
  compareSwipeEventsReady = true;

  let dragging = false;

  const update = event => {
    if (!dragging) return;
    if (event.cancelable) event.preventDefault();
    const rect = stage.getBoundingClientRect();
    setCompareSwipePosition(((event.clientX - rect.left) / rect.width) * 100);
  };

  stage.addEventListener('pointerdown', event => {
    if (event.target.closest('.leaflet-control')) return;
    dragging = true;
    if (stage.setPointerCapture) stage.setPointerCapture(event.pointerId);
    update(event);
  });
  stage.addEventListener('pointermove', update);
  stage.addEventListener('pointerup', event => {
    dragging = false;
    if (stage.hasPointerCapture?.(event.pointerId)) stage.releasePointerCapture(event.pointerId);
  });
  stage.addEventListener('pointercancel', () => { dragging = false; });

  window.addEventListener('resize', () => requestAnimationFrame(() => setCompareSwipePosition(compareSwipePercent)));
}

ensureCompareMaps = function() {
  injectCompareSwipeStyles();
  if (compareSwipeMap) {
    if (compareSwipeBaseLayer && !compareSwipeMap.hasLayer(compareSwipeBaseLayer)) {
      compareSwipeBaseLayer.addTo(compareSwipeMap);
    }
    return;
  }

  const container = document.getElementById('compare-container');
  if (!container) return;

  container.innerHTML = `
    <div id="compare-swipe-map" class="compare-swipe-map"></div>
    <div id="comp-label-before" class="compare-swipe-label before">Before</div>
    <div id="comp-label-after" class="compare-swipe-label after">After</div>
    <div id="compare-swipe-divider" class="compare-swipe-divider">
      <div class="compare-swipe-handle">↔</div>
    </div>
    <div class="compare-swipe-caption">ลากเส้นเพื่อเปรียบเทียบ Before / After</div>
  `;

  compareSwipeMap = L.map('compare-swipe-map', {
    zoomControl:true,
    attributionControl:true,
    dragging:false,
    scrollWheelZoom:false,
    doubleClickZoom:false,
    boxZoom:false,
    keyboard:false
  }).setView([12.75,101.80],15);

  compareSwipeBaseLayer = L.tileLayer(ESRI_WORLD_IMAGERY, {
    maxZoom:19,
    attribution:'Tiles &copy; Esri'
  }).addTo(compareSwipeMap);

  compareSwipeMap.createPane('compareAfterPane');
  compareSwipeMap.getPane('compareAfterPane').style.zIndex = 410;
  compareSwipeMap.createPane('compareBeforePane');
  compareSwipeMap.getPane('compareBeforePane').style.zIndex = 420;
  compareSwipeMap.createPane('compareBoundaryPane');
  compareSwipeMap.getPane('compareBoundaryPane').style.zIndex = 430;

  compareSwipeMap.on('zoom move resize', () => {
    requestAnimationFrame(() => setCompareSwipePosition(compareSwipePercent));
  });

  bindCompareSwipeEvents();
};

function replaceSwipeBoundary(plot, show) {
  if (compareSwipeBoundaryLayer && compareSwipeMap.hasLayer(compareSwipeBoundaryLayer)) {
    compareSwipeMap.removeLayer(compareSwipeBoundaryLayer);
  }
  compareSwipeBoundaryLayer = L.geoJSON({
    type:'Feature', properties:{}, geometry:plot.geometry
  }, {
    pane:'compareBoundaryPane',
    style:{ color:'#34d399', weight:2, opacity:1, fillOpacity:0 }
  });
  if (show) compareSwipeBoundaryLayer.addTo(compareSwipeMap);
}

updateCompareView = async function() {
  if (!activePlot) return;
  ensureCompareMaps();
  if (!compareSwipeMap) return;

  const beforeIndex = Math.max(0, Math.min(11,
    parseInt(document.getElementById('comp-left-select')?.value || '0', 10)
  ));
  const afterIndex = Math.max(0, Math.min(11,
    parseInt(document.getElementById('comp-right-select')?.value || '11', 10)
  ));
  const mode = document.getElementById('comp-mode-select')?.value || 'rgb';
  const beforeItem = activePlot.timeseries[beforeIndex];
  const afterItem = activePlot.timeseries[afterIndex];
  if (!beforeItem || !afterItem) return;

  let beforePrefix = 'rgb';
  let afterPrefix = 'rgb';
  if (mode === 'ndvi') beforePrefix = afterPrefix = 'ndvi';
  if (mode === 'rgb_vs_ndvi') afterPrefix = 'ndvi';

  const beforeUrl = compareSwipeImageUrl(activePlot, beforePrefix, beforeItem);
  const afterUrl = compareSwipeImageUrl(activePlot, afterPrefix, afterItem);
  const token = ++compareSwipeRequestToken;

  // Keep the current comparison visible until both replacement frames are ready.
  try {
    await Promise.all([preloadImage(beforeUrl), preloadImage(afterUrl)]);
  } catch (error) {
    if (token !== compareSwipeRequestToken) return;
    console.warn('Compare image preload failed:', error);
    return;
  }
  if (token !== compareSwipeRequestToken) return;

  const oldBefore = compareSwipeBeforeOverlay;
  const oldAfter = compareSwipeAfterOverlay;

  const nextAfter = L.imageOverlay(afterUrl, imageBoundsForPlot(activePlot), {
    opacity:1, interactive:false, pane:'compareAfterPane', className:'sentinel-overlay'
  }).addTo(compareSwipeMap);
  const nextBefore = L.imageOverlay(beforeUrl, imageBoundsForPlot(activePlot), {
    opacity:1, interactive:false, pane:'compareBeforePane', className:'sentinel-overlay'
  }).addTo(compareSwipeMap);

  compareSwipeAfterOverlay = nextAfter;
  compareSwipeBeforeOverlay = nextBefore;

  const finishSwap = () => {
    if (token !== compareSwipeRequestToken) return;
    setCompareSwipePosition(compareSwipePercent);
    if (oldBefore && compareSwipeMap.hasLayer(oldBefore)) compareSwipeMap.removeLayer(oldBefore);
    if (oldAfter && compareSwipeMap.hasLayer(oldAfter)) compareSwipeMap.removeLayer(oldAfter);
    if (compareSwipeBoundaryLayer) compareSwipeBoundaryLayer.bringToFront?.();
  };
  nextBefore.once('load', () => requestAnimationFrame(finishSwap));

  const beforeLabel = document.getElementById('comp-label-before');
  const afterLabel = document.getElementById('comp-label-after');
  if (beforeLabel) beforeLabel.textContent = `${thaiMonths[beforeItem.month_num]} ${beforeItem.year} • ${beforePrefix.toUpperCase()}`;
  if (afterLabel) afterLabel.textContent = `${thaiMonths[afterItem.month_num]} ${afterItem.year} • ${afterPrefix.toUpperCase()}`;

  const showBoundary = document.getElementById('comp-boundary-toggle')?.checked !== false;
  replaceSwipeBoundary(activePlot, showBoundary);

  const bounds = compareSwipeBoundaryLayer.getBounds();
  if (bounds.isValid()) {
    compareSwipeMap.fitBounds(bounds, { padding:[40,40], maxZoom:17, animate:false });
  }
  comparePlotId = activePlot.id;

  requestAnimationFrame(() => {
    compareSwipeMap.invalidateSize();
    setCompareSwipePosition(compareSwipePercent);
  });

  const leftNdvi = beforeItem.mean_ndvi_inside;
  const rightNdvi = afterItem.mean_ndvi_inside;
  const statText = document.getElementById('comp-in-stat-text');
  const gainPill = document.getElementById('comp-gain-pill');
  if (isFiniteNumber(leftNdvi) && isFiniteNumber(rightNdvi)) {
    const diff = rightNdvi - leftNdvi;
    if (statText) statText.innerHTML = `Mean NDVI: <strong>${leftNdvi.toFixed(3)}</strong> ➔ <strong>${rightNdvi.toFixed(3)}</strong>`;
    if (gainPill) gainPill.textContent = `${diff >= 0 ? '+' : ''}${diff.toFixed(3)}`;
  } else {
    if (statText) statText.textContent = 'Verified NDVI statistics ยังไม่ถูกสร้าง — แต่ Before/After swipe ใช้งานได้';
    if (gainPill) gainPill.textContent = 'No verified metric';
  }
};

toggleCompareBoundary = function(show) {
  if (!compareSwipeMap || !compareSwipeBoundaryLayer) return;
  if (show && !compareSwipeMap.hasLayer(compareSwipeBoundaryLayer)) {
    compareSwipeBoundaryLayer.addTo(compareSwipeMap);
    compareSwipeBoundaryLayer.bringToFront?.();
  }
  if (!show && compareSwipeMap.hasLayer(compareSwipeBoundaryLayer)) {
    compareSwipeMap.removeLayer(compareSwipeBoundaryLayer);
  }
};

document.addEventListener('DOMContentLoaded', () => {
  injectCompareSwipeStyles();
  const hint = document.querySelector('.compare-hint');
  if (hint) hint.textContent = 'ลากเส้นแบ่งกลางไปทางซ้ายหรือขวาเพื่อเปรียบเทียบ Before / After บนแผนที่เดียวกัน; Esri World Imagery เป็นพื้นหลัง';
});
