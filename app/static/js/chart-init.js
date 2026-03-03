/**
 * chart-init.js — Chart.js shared helpers for trend charts
 */

/**
 * Build a line chart on a canvas element.
 * @param {string} canvasId - The canvas element id
 * @param {string[]} labels - X-axis labels
 * @param {object[]} datasets - Chart.js datasets array
 * @returns {Chart} The created Chart instance
 */
function buildLineChart(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  // Destroy existing chart if any
  if (ctx._chartInstance) {
    ctx._chartInstance.destroy();
  }

  const chart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', labels: { font: { size: 12 }, boxWidth: 12 } },
        tooltip: {
          backgroundColor: 'rgba(0,0,0,0.7)',
          padding: 8,
          cornerRadius: 6,
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(0,0,0,0.04)' },
          ticks: { font: { size: 11 }, maxTicksLimit: 10 },
        },
        y: {
          grid: { color: 'rgba(0,0,0,0.04)' },
          ticks: { font: { size: 11 } },
        },
      },
    },
  });

  ctx._chartInstance = chart;
  return chart;
}

/**
 * Default dataset style for blood pressure systolic line.
 */
function bpSystolicDataset(data) {
  return {
    label: '收缩压',
    data,
    borderColor: '#ef4444',
    backgroundColor: 'rgba(239,68,68,0.08)',
    borderWidth: 2,
    pointRadius: 3,
    tension: 0.3,
    fill: false,
  };
}

/**
 * Default dataset style for blood pressure diastolic line.
 */
function bpDiastolicDataset(data) {
  return {
    label: '舒张压',
    data,
    borderColor: '#f97316',
    backgroundColor: 'rgba(249,115,22,0.08)',
    borderWidth: 2,
    pointRadius: 3,
    tension: 0.3,
    fill: false,
  };
}

/**
 * Default dataset style for blood glucose line.
 */
function glucoseDataset(data) {
  return {
    label: '血糖',
    data,
    borderColor: '#8b5cf6',
    backgroundColor: 'rgba(139,92,246,0.08)',
    borderWidth: 2,
    pointRadius: 3,
    tension: 0.3,
    fill: true,
  };
}

/**
 * Default dataset style for weight line.
 */
function weightDataset(data) {
  return {
    label: '体重 (kg)',
    data,
    borderColor: '#16a34a',
    backgroundColor: 'rgba(22,163,74,0.08)',
    borderWidth: 2,
    pointRadius: 3,
    tension: 0.3,
    fill: true,
  };
}
