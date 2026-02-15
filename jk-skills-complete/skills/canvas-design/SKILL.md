---
name: canvas-design
description: "Create graphics and designs using HTML Canvas. Use for generating images, charts, and visual content."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Canvas Design

## Basic Canvas Setup
```html
<canvas id="canvas" width="800" height="600"></canvas>
<script>
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
</script>
```

## Drawing Shapes
```javascript
// Rectangle
ctx.fillStyle = '#3498db';
ctx.fillRect(50, 50, 200, 100);

// Circle
ctx.beginPath();
ctx.arc(300, 200, 50, 0, Math.PI * 2);
ctx.fillStyle = '#e74c3c';
ctx.fill();

// Line
ctx.beginPath();
ctx.moveTo(50, 300);
ctx.lineTo(250, 350);
ctx.strokeStyle = '#2ecc71';
ctx.lineWidth = 3;
ctx.stroke();

// Rounded rectangle
function roundedRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
  ctx.fill();
}
```

## Text
```javascript
ctx.font = 'bold 24px Arial';
ctx.fillStyle = '#333';
ctx.textAlign = 'center';
ctx.fillText('Hello World', canvas.width/2, 100);
```

## Gradients
```javascript
const gradient = ctx.createLinearGradient(0, 0, 200, 0);
gradient.addColorStop(0, '#ff6b6b');
gradient.addColorStop(1, '#4ecdc4');
ctx.fillStyle = gradient;
ctx.fillRect(0, 0, 200, 100);
```

## Export as Image
```javascript
const dataURL = canvas.toDataURL('image/png');
// Or download
const link = document.createElement('a');
link.download = 'design.png';
link.href = dataURL;
link.click();
```
