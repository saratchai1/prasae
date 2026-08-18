// Adjustable Sentinel/NDVI opacity controls for Detail and Before/After views.
// Loaded after app.js and compare-swipe.js so it can reuse their Leaflet overlay state
// without replacing plot-selection or compare-swipe logic.

(() => {
  const DEFAULT_OPACITY = 0.85;
  const DETAIL_STORAGE_KEY = 'prasae-detail-overlay-opacity';
  const COMPARE_STORAGE_KEY = 'prasae-compare-overlay-opacity';

  function clampOpacity(value, fallback = DEFAULT_OPACITY) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return fallback;
    return Math.max(0, Math.min(1, numeric));
  }

  function readStoredOpacity(key) {
    try {
      return clampOpacity(localStorage.getItem(key));
    } catch (_) {
      return DEFAULT_OPACITY;
    }
  }

  function saveOpacity(key, value) {
    try {
      localStorage.setItem(key, String(value));
    } catch (_) {
      // Storage can be unavailable in private/restricted browser contexts.
    }
  }

  let detailOpacity = readStoredOpacity(DETAIL_STORAGE_KEY);
  let compareOpacity = readStoredOpacity(COMPARE_STORAGE_KEY);

  function applyDetailOpacity() {
    try {
      if (typeof currentSentinelOverlay !== 'undefined' && currentSentinelOverlay?.setOpacity) {
        currentSentinelOverlay.setOpacity(detailOpacity);
      }
      if (typeof pendingSentinelOverlay !== 'undefined' && pendingSentinelOverlay?.setOpacity) {
        pendingSentinelOverlay.setOpacity(detailOpacity);
      }
    } catch (error) {
      console.warn('Unable to apply Detail overlay opacity:', error);
    }
  }

  function applyCompareOpacity() {
    try {
      if (typeof compareSwipeBeforeOverlay !== 'undefined' && compareSwipeBeforeOverlay?.setOpacity) {
        compareSwipeBeforeOverlay.setOpacity(compareOpacity);
      }
      if (typeof compareSwipeAfterOverlay !== 'undefined' && compareSwipeAfterOverlay?.setOpacity) {
        compareSwipeAfterOverlay.setOpacity(compareOpacity);
      }
    } catch (error) {
      console.warn('Unable to apply Compare overlay opacity:', error);
    }
  }

  function setDetailOpacityFromPercent(percent) {
    detailOpacity = clampOpacity(Number(percent) / 100);
    saveOpacity(DETAIL_STORAGE_KEY, detailOpacity);
    const value = document.getElementById('detail-overlay-opacity-value');
    if (value) value.textContent = `${Math.round(detailOpacity * 100)}%`;
    applyDetailOpacity();
  }

  function setCompareOpacityFromPercent(percent) {
    compareOpacity = clampOpacity(Number(percent) / 100);
    saveOpacity(COMPARE_STORAGE_KEY, compareOpacity);
    const value = document.getElementById('compare-overlay-opacity-value');
    if (value) value.textContent = `${Math.round(compareOpacity * 100)}%`;
    applyCompareOpacity();
  }

  function makeOpacityControl({ idPrefix, label, opacity, onInput }) {
    const wrapper = document.createElement('div');
    wrapper.className = 'sat-opacity-control';
    wrapper.innerHTML = `
      <div class="sat-opacity-label-row">
        <span class="sat-opacity-label">${label}</span>
        <strong id="${idPrefix}-overlay-opacity-value">${Math.round(opacity * 100)}%</strong>
      </div>
      <div class="sat-opacity-slider-row">
        <span class="sat-opacity-end">Esri</span>
        <input
          id="${idPrefix}-overlay-opacity-slider"
          class="sat-opacity-slider"
          type="range"
          min="0"
          max="100"
          step="1"
          value="${Math.round(opacity * 100)}"
          aria-label="${label}"
        >
        <span class="sat-opacity-end">Sentinel</span>
      </div>`;

    wrapper.querySelector('input')?.addEventListener('input', event => onInput(event.target.value));
    return wrapper;
  }

  function injectStyles() {
    if (document.getElementById('sat-opacity-control-styles')) return;
    const style = document.createElement('style');
    style.id = 'sat-opacity-control-styles';
    style.textContent = `
      .sat-opacity-control {
        min-width:220px;
        padding:7px 10px;
        border:1px solid rgba(255,255,255,.10);
        border-radius:9px;
        background:rgba(15,23,42,.55);
      }
      .sat-opacity-label-row,
      .sat-opacity-slider-row {
        display:flex;
        align-items:center;
        gap:8px;
      }
      .sat-opacity-label-row {
        justify-content:space-between;
        margin-bottom:4px;
        color:#cbd5e1;
        font-size:.68rem;
        line-height:1.2;
      }
      .sat-opacity-label-row strong {
        color:#f8fafc;
        font-size:.72rem;
        min-width:34px;
        text-align:right;
      }
      .sat-opacity-slider-row { width:100%; }
      .sat-opacity-end {
        color:#64748b;
        font-size:.58rem;
        white-space:nowrap;
      }
      .sat-opacity-slider {
        width:130px;
        min-width:90px;
        accent-color:#38bdf8;
        cursor:pointer;
      }
      .compare-selectors .sat-opacity-control {
        align-self:flex-end;
        min-width:235px;
      }
      @media (max-width:900px) {
        .sat-opacity-control { width:100%; min-width:0; }
        .sat-opacity-slider { flex:1; width:auto; }
      }
    `;
    document.head.appendChild(style);
  }

  function injectControls() {
    injectStyles();

    const viewerToolbar = document.querySelector('#panel-detail .viewer-toolbar');
    if (viewerToolbar && !document.getElementById('detail-overlay-opacity-slider')) {
      const control = makeOpacityControl({
        idPrefix: 'detail',
        label: 'ความทึบ / โปร่งแสงภาพดาวเทียม',
        opacity: detailOpacity,
        onInput: setDetailOpacityFromPercent
      });
      const boundaryToggle = viewerToolbar.querySelector('.boundary-toggle');
      viewerToolbar.insertBefore(control, boundaryToggle || null);
    }

    const compareSelectors = document.querySelector('#panel-compare .compare-selectors');
    if (compareSelectors && !document.getElementById('compare-overlay-opacity-slider')) {
      compareSelectors.appendChild(makeOpacityControl({
        idPrefix: 'compare',
        label: 'ความทึบ Before / After',
        opacity: compareOpacity,
        onInput: setCompareOpacityFromPercent
      }));
    }
  }

  // Re-apply the chosen opacity whenever Detail creates a replacement image overlay.
  if (typeof updateGeeOverlay === 'function') {
    const originalUpdateGeeOverlay = updateGeeOverlay;
    updateGeeOverlay = async function(...args) {
      const result = await originalUpdateGeeOverlay.apply(this, args);
      const pending = typeof pendingSentinelOverlay !== 'undefined' ? pendingSentinelOverlay : null;
      if (pending?.once) {
        pending.once('load', () => {
          requestAnimationFrame(() => {
            if (pending?.setOpacity) pending.setOpacity(detailOpacity);
            applyDetailOpacity();
          });
          setTimeout(applyDetailOpacity, 320);
        });
      }
      // Covers browser-cache timing where Leaflet's load event may fire very quickly.
      requestAnimationFrame(applyDetailOpacity);
      setTimeout(applyDetailOpacity, 60);
      setTimeout(applyDetailOpacity, 360);
      return result;
    };
  }

  // Re-apply the chosen opacity whenever Compare creates new Before/After overlays.
  if (typeof updateCompareView === 'function') {
    const originalUpdateCompareView = updateCompareView;
    updateCompareView = async function(...args) {
      const result = await originalUpdateCompareView.apply(this, args);
      applyCompareOpacity();
      requestAnimationFrame(applyCompareOpacity);
      setTimeout(applyCompareOpacity, 60);
      return result;
    };
  }

  document.addEventListener('DOMContentLoaded', () => {
    injectControls();
    setDetailOpacityFromPercent(detailOpacity * 100);
    setCompareOpacityFromPercent(compareOpacity * 100);
  });
})();
