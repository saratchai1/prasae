import re

with open('app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update initCompareSelectors to call updateCompareView
if 'rightSel.value = 35; // Aug 2026\n}' in content:
    content = content.replace(
        'rightSel.value = 35; // Aug 2026\n}', 
        'rightSel.value = 35; // Aug 2026\n  updateCompareView();\n}'
    )

# 2. Replace updateCompareView
old_update = """function updateCompareView() {
  // Handled smoothly
}"""

new_update = """function updateCompareView() {
  if (!activePlot) return;
  
  const leftIdx = parseInt(document.getElementById('comp-left-select').value, 10);
  const rightIdx = parseInt(document.getElementById('comp-right-select').value, 10);
  
  const itemL = activePlot.timeseries[leftIdx];
  const itemR = activePlot.timeseries[rightIdx];
  
  if (!itemL || !itemR) return;
  
  document.getElementById('comp-label-before').textContent = `${thaiMonths[itemL.month_num]} ${itemL.year}`;
  document.getElementById('comp-label-after').textContent = `${thaiMonths[itemR.month_num]} ${itemR.year}`;
  
  const getClosest = (y, m) => {
    const targetVal = y * 12 + m;
    let closest = MILESTONE_MONTHS[0];
    let minDiff = 999;
    MILESTONE_MONTHS.forEach(ms => {
      const [yy, mm] = ms.split('-').map(Number);
      const val = yy * 12 + mm;
      if (Math.abs(val - targetVal) < minDiff) {
        minDiff = Math.abs(val - targetVal);
        closest = ms;
      }
    });
    return closest;
  };
  
  const msL = getClosest(itemL.year, itemL.month_num);
  const msR = getClosest(itemR.year, itemR.month_num);
  
  const imgL = `data/plots/${activePlot.id}/rgb_${msL}.png`;
  const imgR = `data/plots/${activePlot.id}/rgb_${msR}.png`;
  
  const beforeMap = document.getElementById('compare-before-map');
  const afterMap = document.getElementById('compare-after-map');
  
  beforeMap.style.backgroundImage = `url(${imgL})`;
  beforeMap.style.backgroundSize = '100% 100%';
  beforeMap.style.backgroundPosition = 'center';
  beforeMap.style.backgroundRepeat = 'no-repeat';

  afterMap.style.backgroundImage = `url(${imgR})`;
  afterMap.style.backgroundSize = '100% 100%';
  afterMap.style.backgroundPosition = 'center';
  afterMap.style.backgroundRepeat = 'no-repeat';
}

function initCompareSlider() {
  const container = document.getElementById('compare-container');
  const wrapper = document.getElementById('comp-before-wrapper');
  const divider = document.getElementById('comp-divider');
  let isDragging = false;

  if (!container || !wrapper || !divider) return;

  const slide = (e) => {
    if (!isDragging) return;
    const rect = container.getBoundingClientRect();
    // Support touch and mouse
    let clientX = e.clientX;
    if (e.touches && e.touches.length > 0) clientX = e.touches[0].clientX;
    
    let x = clientX - rect.left;
    x = Math.max(0, Math.min(x, rect.width));
    const pct = (x / rect.width) * 100;
    wrapper.style.width = pct + '%';
    divider.style.left = pct + '%';
  };

  divider.addEventListener('mousedown', () => isDragging = true);
  divider.addEventListener('touchstart', () => isDragging = true);
  
  window.addEventListener('mouseup', () => isDragging = false);
  window.addEventListener('touchend', () => isDragging = false);
  
  window.addEventListener('mousemove', slide);
  window.addEventListener('touchmove', slide);
}

document.addEventListener('DOMContentLoaded', initCompareSlider);
"""

content = content.replace(old_update, new_update)

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Compare tab patched successfully!")
