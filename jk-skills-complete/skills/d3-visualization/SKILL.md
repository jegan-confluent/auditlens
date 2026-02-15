---
name: d3-visualization
description: "Create data visualizations with D3.js. Use for interactive charts and graphs."
allowed-tools: "Read,Write"
version: 1.0.0
---

# D3.js Visualization

## Basic Bar Chart
```javascript
const data = [10, 20, 30, 40, 50];
const width = 500, height = 300;

const svg = d3.select('#chart')
  .append('svg')
  .attr('width', width)
  .attr('height', height);

const xScale = d3.scaleBand()
  .domain(data.map((_, i) => i))
  .range([0, width])
  .padding(0.1);

const yScale = d3.scaleLinear()
  .domain([0, d3.max(data)])
  .range([height, 0]);

svg.selectAll('rect')
  .data(data)
  .enter()
  .append('rect')
  .attr('x', (d, i) => xScale(i))
  .attr('y', d => yScale(d))
  .attr('width', xScale.bandwidth())
  .attr('height', d => height - yScale(d))
  .attr('fill', '#3498db');
```

## Line Chart
```javascript
const line = d3.line()
  .x((d, i) => xScale(i))
  .y(d => yScale(d))
  .curve(d3.curveMonotoneX);

svg.append('path')
  .datum(data)
  .attr('fill', 'none')
  .attr('stroke', '#e74c3c')
  .attr('stroke-width', 2)
  .attr('d', line);
```

## Pie Chart
```javascript
const pie = d3.pie();
const arc = d3.arc().innerRadius(0).outerRadius(100);

svg.selectAll('path')
  .data(pie(data))
  .enter()
  .append('path')
  .attr('d', arc)
  .attr('fill', (d, i) => d3.schemeCategory10[i]);
```

## Responsive
```javascript
function resize() {
  const width = container.clientWidth;
  svg.attr('width', width);
  xScale.range([0, width]);
  // Update elements
}
window.addEventListener('resize', resize);
```
