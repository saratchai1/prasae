// Final PDD22 chart wording hotfix: second series is FCD Green, not NDVI vegetation proxy.
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
})();
