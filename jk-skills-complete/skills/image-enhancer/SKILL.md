---
name: image-enhancer
description: "Enhance and process images programmatically. Use for image optimization and manipulation."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Image Enhancer

## Using Sharp (Node.js)
```javascript
const sharp = require('sharp');

// Resize
await sharp('input.jpg')
  .resize(800, 600, { fit: 'cover' })
  .toFile('output.jpg');

// Format conversion
await sharp('input.png')
  .webp({ quality: 80 })
  .toFile('output.webp');

// Enhance
await sharp('input.jpg')
  .sharpen()
  .normalize()
  .modulate({ brightness: 1.1, saturation: 1.2 })
  .toFile('enhanced.jpg');
```

## Using Pillow (Python)
```python
from PIL import Image, ImageEnhance, ImageFilter

img = Image.open('input.jpg')

# Resize
img = img.resize((800, 600), Image.LANCZOS)

# Enhance
enhancer = ImageEnhance.Contrast(img)
img = enhancer.enhance(1.2)

enhancer = ImageEnhance.Sharpness(img)
img = enhancer.enhance(1.5)

# Filter
img = img.filter(ImageFilter.SHARPEN)

img.save('output.jpg', quality=85)
```

## Batch Processing
```python
from pathlib import Path

input_dir = Path('images')
output_dir = Path('processed')
output_dir.mkdir(exist_ok=True)

for img_path in input_dir.glob('*.jpg'):
    img = Image.open(img_path)
    img = img.resize((1200, 800), Image.LANCZOS)
    img.save(output_dir / img_path.name, quality=85)
```

## Optimization Tips
- Use WebP for web (30% smaller)
- Lazy load below-fold images
- Serve responsive sizes
- Use CDN with auto-optimization
