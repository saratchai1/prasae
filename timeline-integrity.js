// Timeline integrity hotfix: actual available dates only, decoded frame swaps, robust compare selectors.
(() => {
  const availabilityCache = new Map();
  let selectionToken = 0;

  function seriesSource(plot) {
    if (!plot) return [];
    if (!Array.isArray(plot._declaredTimeseries)) {
      plot._declaredTimeseries = Array.isArray(plot.timeseries) ? plot.timeseries.slice() : [];
    }
    return plot._declaredTimeseries;
  }

  function assetUrl(plotId, prefix, month) {
    return `data/plots/${plotId}/${prefix}_${month}.png?v=${ASSET_VERSION}`;
  }

  async function assetExists(url) {
    try {
      const response = await fetch(url, { method:'HEAD', cache:'no-store' });
      if (response.ok) return true;
      if (response.status !== 405) return false;
    } catch (_) {}

    return new Promise(resolve => {
      const image = new Image();
      image.onload = () => resolve(true);
      image.onerror = () => resolve(false);
      image.src = url;
    });
  }

  async function availableSeries(plot) {
    const declared = seriesSource(plot).filter(item => item && MILESTONE_MONTHS.includes(item.month));
    if (availabilityCache.has(plot.id)) {
      const months = availabilityCache.get(plot.id);
      return declared.filter(item => months.has(item.month));
    }

    const checks = await Promise.all(declared.map(async item => {
      // RGB is the canonical timeline frame. Proper composites generate RGB + NDVI together.
      const exists = await assetExists(assetUrl(plot.id, 'rgb', item.month));
      return [item.month, exists];
    }));
    const months = new Set(checks.filter(([,exists]) => exists).map(([month]) => month));
    availabilityCache.set(plot.id, months);
    return declared.filter(item => months.has(item.month));
  }

  function formatShort(item) {
    return item ? `${thaiMonths[item.month_num]} ${item.year}` : 'ไม่มีภาพ';
  }

  function updateTimelineChrome(series) {
    const slider = document.getElementById('month-slider');
    if (slider) {
      slider.min = '0';
      slider.max = String(Math.max(0, series.length - 1));
      slider.step = '1';
      slider.disabled = series.length === 0;
      slider.value = String(Math.min(Number(slider.value) || 0, Math.max(0, series.length - 1)));
    }

    const ticks = document.querySelector('.slider-ticks');
    if (ticks) {
      if (!series.length) {
        ticks.innerHTML = '<span>ไม่มีช่วงเวลาที่มีภาพจริง</span>';
      } else {
        const indices = [...new Set([0, Math.round((series.length - 1) / 3), Math.round((series.length - 1) * 2 / 3), series.length - 1])];
        ticks.innerHTML = indices.map(index => `<span>${formatShort(series[index])}</span>`).join('');
      }
    }

    const countText = `${series.length} ช่วงเวลาที่มีภาพจริง`;
    const detailTab = document.getElementById('wtab-detail');
    if (detailTab) detailTab.textContent = `วิเคราะห์ ${countText}`;
    const datePill = document.querySelector('.date-range-pill');
    if (datePill) datePill.textContent = countText;
  }

  // Decode before Leaflet is allowed to swap layers. This removes the one-frame Esri flash.
  preloadImage = function(url) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.decoding = 'async';
      image.onload = async () => {
        try {
          if (typeof image.decode === 'function') await image.decode();
        } catch (_) {
          // The image is already loaded; decode() may reject on browsers that decoded it eagerly.
        }
        resolve(image);
      };
      image.onerror = reject;
      image.src = url;
    });
  };

  const baseSetMonthIndex = setMonthIndex;
  setMonthIndex = function(index) {
    if (!activePlot) return;
    const series = Array.isArray(activePlot.timeseries) ? activePlot.timeseries : [];
    if (!series.length) {
      currentMonthIndex = 0;
      const slider = document.getElementById('month-slider');
      if (slider) { slider.value = '0'; slider.disabled = true; }
      const date = document.getElementById('playback-date-display');
      const hud = document.getElementById('hud-month-label');
      if (date) date.textContent = 'ไม่มีภาพ';
      if (hud) hud.textContent = 'ไม่มีช่วงเวลาที่มีภาพจริง';
      return;
    }
    const safeIndex = Math.max(0, Math.min(series.length - 1, Number(index) || 0));
    baseSetMonthIndex(safeIndex);
  };

  prevMonth = function() {
    const length = activePlot?.timeseries?.length || 0;
    if (!length) return;
    setMonthIndex((currentMonthIndex - 1 + length) % length);
  };

  nextMonth = function() {
    const length = activePlot?.timeseries?.length || 0;
    if (!length) return;
    setMonthIndex((currentMonthIndex + 1) % length);
  };

  initCompareSelectors = function(plot) {
    const left = document.getElementById('comp-left-select');
    const right = document.getElementById('comp-right-select');
    if (!left || !right) return;
    left.innerHTML = '';
    right.innerHTML = '';

    const series = Array.isArray(plot?.timeseries) ? plot.timeseries : [];
    series.forEach((item, index) => {
      const metric = isFiniteNumber(item.mean_ndvi_inside) ? ` • NDVI ${item.mean_ndvi_inside.toFixed(2)}` : '';
      const label = `${formatShort(item)}${metric}`;
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = label;
      left.appendChild(option);
      right.appendChild(option.cloneNode(true));
    });

    left.disabled = series.length === 0;
    right.disabled = series.length === 0;
    if (series.length) {
      left.value = '0';
      right.value = String(series.length - 1);
    }
  };

  // Keep the current satellite layer fully visible until the next decoded layer is ready.
  updateGeeOverlay = async function() {
    if (!activePlot || !plotSatelliteMap || currentPlotLayerKey === 'esri') return;
    const item = activePlot.timeseries?.[currentMonthIndex];
    if (!item || !MILESTONE_MONTHS.includes(item.month)) return;

    const prefix = currentPlotLayerKey === 'gee_ndvi' ? 'ndvi' : 'rgb';
    const url = assetUrl(activePlot.id, prefix, item.month);
    const token = ++sentinelSwapToken;
    const oldOverlay = currentSentinelOverlay;
    let nextOverlay = null;

    try {
      await preloadImage(url);
      if (token !== sentinelSwapToken || currentPlotLayerKey === 'esri') return;

      nextOverlay = L.imageOverlay(url, imageBoundsForPlot(activePlot), {
        opacity:0,
        interactive:false,
        className:'sentinel-overlay'
      });
      pendingSentinelOverlay = nextOverlay;

      await new Promise((resolve, reject) => {
        nextOverlay.once('load', resolve);
        nextOverlay.once('error', reject);
        nextOverlay.addTo(plotSatelliteMap);
      });

      if (token !== sentinelSwapToken || currentPlotLayerKey === 'esri') {
        if (plotSatelliteMap.hasLayer(nextOverlay)) plotSatelliteMap.removeLayer(nextOverlay);
        if (pendingSentinelOverlay === nextOverlay) pendingSentinelOverlay = null;
        return;
      }

      nextOverlay.setOpacity(1);
      await new Promise(resolve => setTimeout(resolve, 300));

      if (token !== sentinelSwapToken || currentPlotLayerKey === 'esri') {
        if (plotSatelliteMap.hasLayer(nextOverlay)) plotSatelliteMap.removeLayer(nextOverlay);
        return;
      }

      if (oldOverlay && oldOverlay !== nextOverlay && plotSatelliteMap.hasLayer(oldOverlay)) {
        plotSatelliteMap.removeLayer(oldOverlay);
      }
      currentSentinelOverlay = nextOverlay;
      pendingSentinelOverlay = null;
      if (plotBoundaryLayer) plotBoundaryLayer.bringToFront();
    } catch (error) {
      if (nextOverlay && plotSatelliteMap.hasLayer(nextOverlay)) plotSatelliteMap.removeLayer(nextOverlay);
      if (pendingSentinelOverlay === nextOverlay) pendingSentinelOverlay = null;
      if (oldOverlay && plotSatelliteMap.hasLayer(oldOverlay)) oldOverlay.setOpacity(1);
      if (token === sentinelSwapToken) console.warn('Satellite frame unavailable; keeping previous frame:', error);
    }
  };

  const baseSelectPlot = selectPlot;
  selectPlot = async function(plotId) {
    const plot = allPlotsData.find(item => item.id === Number(plotId));
    if (!plot) return;
    const token = ++selectionToken;

    const series = await availableSeries(plot);
    if (token !== selectionToken) return;

    plot.timeseries = series;
    currentMonthIndex = Math.min(currentMonthIndex, Math.max(0, series.length - 1));
    updateTimelineChrome(series);
    baseSelectPlot(plotId);

    // baseSelectPlot calls the overridden chart/timeline/compare functions using the filtered series.
    updateTimelineChrome(series);
    if (!series.length) {
      pause();
      renderPlotChart(plot);
      initCompareSelectors(plot);
    }
  };

  // compare-swipe.js already keeps an independent Esri base layer. Guard its selectors against filtered series.
  const baseUpdateCompareView = updateCompareView;
  updateCompareView = async function() {
    if (!activePlot?.timeseries?.length) {
      const stat = document.getElementById('comp-in-stat-text');
      const pill = document.getElementById('comp-gain-pill');
      if (stat) stat.textContent = 'ไม่มีช่วงเวลาที่มีภาพจริงสำหรับแปลงนี้';
      if (pill) pill.textContent = 'No imagery';
      ensureCompareMaps();
      return;
    }
    return baseUpdateCompareView();
  };
})();
