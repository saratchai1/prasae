'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const U = require('../unified-data.js');
const observation = (month, secondary) => ({month, status:'observed_single_scene', clear_pixel_pct:100,
  proxy_area_rai:40, mean_ndvi_inside:.6, secondary:{status:secondary, reason:'ภาพครบ แต่ค่าระหว่างชุดข้อมูลยังเทียบกันไม่ได้'}});
const plot = {id:1, registryId:1, scope:'registry', area_rai:100,
  timeseries:[observation('2024-09','CLEAR'), observation('2025-09','RADIOMETRY_REVIEW')]};

test('native imagery remains available while mixed radiometry is excluded from deltas', () => {
  const o = plot.timeseries[1];
  assert.equal(U.quality(plot,o).status,'RADIOMETRY_REVIEW');
  assert.equal(U.quality(plot,o).eligible,false);
  assert.equal(U.ndvi(plot,o),null);
  assert.equal(U.green(plot,o),null);
  assert.deepEqual(U.asset(plot,o,'gee_rgb'),{state:'AVAILABLE',url:'data/plots/1/rgb_2025-09.png'});
  assert.equal(U.asset(plot,o,'gee_ndvi').state,'AVAILABLE');
  const result=U.compare(plot,'2024-09','2025-09');
  assert.equal(result.status,'RADIOMETRY_REVIEW');
  assert.equal(result.delta,null);
  assert.equal(result.deltaNdvi,null);
  assert.equal(U.summarize([plot],'2024-09','2025-09').qualityReview,1);
});

test('legacy screening and comparison remain available', () => {
  const legacy={...plot,timeseries:[observation('2024-09','CLEAR'),observation('2025-09','CLEAR')]};
  assert.equal(U.quality(legacy,legacy.timeseries[0]).eligible,true);
  assert.equal(U.compare(legacy,'2024-09','2025-09').delta,0);
});
