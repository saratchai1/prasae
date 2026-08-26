// Final PDD22 UI hotfixes: correct chart labels and restore draggable Before/After swipe.
(() => {
  const baseSelectPlot = selectPlot;
  selectPlot = function pdd22ChartLabelSelect(plotId) {
    baseSelectPlot(plotId);
    const title = document.getElementById('chart-plot-title');
    if (title && activePlot) title.textContent = `NDVI + FCD Green — ${activePlot.code}`;
    if (plotNdviChart?.data?.datasets?.[0]) {
      plotNdviChart.data.datasets[0].label = 'Mean NDVI — cleaned Sentinel-2';
    }
    if (plotNdviChart?.data?.datasets?.[1]) {
      plotNdviChart.data.datasets[1].label = 'FCD Green % — QA GOOD only';
    }
    if (plotNdviChart) plotNdviChart.update('none');
  };

  // Load after pdd22-production.js so the swipe implementation wins over
  // the temporary side-by-side compare override.
  const swipe = document.createElement('script');
  swipe.src = 'pdd22-compare-swipe.js?v=20260826-1425';
  swipe.defer = true;
  swipe.onload = () => {
    const hint = document.querySelector('.compare-hint');
    if (hint) hint.textContent = 'ลากเส้นแบ่งกลางไปทางซ้ายหรือขวาเพื่อเปรียบเทียบ Before / After บนแผนที่เดียวกัน';
    if (document.getElementById('panel-compare')?.classList.contains('active') && activePlot) {
      updateCompareView();
    }
  };
  document.head.appendChild(swipe);
})();
