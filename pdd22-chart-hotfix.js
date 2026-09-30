// Presentation adapter only. No script injection or selectPlot wrapping.
(() => {
  const baseRender = renderPlotChart;
  renderPlotChart = function renderQaAuditedChart(plot) {
    const M = Pdd22Observations;
    const audited = {...plot,timeseries:plot.timeseries.map(item => ({...item,
      mean_ndvi_inside:M.ndvi(item),
      vegetation_coverage_proxy_pct:M.goodFcd(plot.fcd_by_month?.[item.month])
        ? plot.fcd_by_month[item.month].green_rai / plot.area_rai * 100 : null
    }))};
    baseRender(audited);
    document.getElementById('chart-plot-title').textContent=`NDVI + FCD เขียว · ${plot.code}`;
    if (!plotNdviChart) return;
    plotNdviChart.data.labels=plot.timeseries.map(i=>Pdd22Ui.monthLabel(i.month));
    plotNdviChart.data.datasets[0].label='NDVI · QA GOOD เท่านั้น';
    plotNdviChart.data.datasets[1].label='FCD เขียว (%) · QA GOOD เท่านั้น';
    plotNdviChart.data.datasets.forEach(d=>{d.spanGaps=false;d.tension=0;});
    const status=document.querySelector('.integrity-chart-status');
    if(status)status.textContent='ไม่มีค่าที่ผ่าน QA GOOD · ไม่แสดงค่าจาก NO_DATA/LOW_QA แทน';
    plotNdviChart.update('none');
  };
})();
