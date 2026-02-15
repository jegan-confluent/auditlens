---
name: pptx-builder
description: "PowerPoint presentation creation with slides, charts, and images. Use when generating presentations."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# PowerPoint Builder

## Basic Presentation
```python
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation()

# Title slide
slide_layout = prs.slide_layouts[0]
slide = prs.slides.add_slide(slide_layout)
title = slide.shapes.title
subtitle = slide.placeholders[1]

title.text = "Presentation Title"
subtitle.text = "By Author Name"

# Content slide
slide_layout = prs.slide_layouts[1]
slide = prs.slides.add_slide(slide_layout)
title = slide.shapes.title
title.text = "Slide Title"

body = slide.shapes.placeholders[1]
tf = body.text_frame
tf.text = "First bullet point"
p = tf.add_paragraph()
p.text = "Second bullet point"
p.level = 1

prs.save("presentation.pptx")
```

## Add Chart
```python
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE

chart_data = CategoryChartData()
chart_data.categories = ['Q1', 'Q2', 'Q3', 'Q4']
chart_data.add_series('Sales', (100, 200, 150, 300))

x, y, cx, cy = Inches(2), Inches(2), Inches(6), Inches(4)
slide.shapes.add_chart(
    XL_CHART_TYPE.COLUMN_CLUSTERED, x, y, cx, cy, chart_data
)
```

## Add Image
```python
slide.shapes.add_picture('image.png', Inches(1), Inches(1), width=Inches(4))
```

## Add Table
```python
rows, cols = 3, 4
table = slide.shapes.add_table(rows, cols, Inches(1), Inches(2), Inches(8), Inches(2)).table

# Set header row
for i, header in enumerate(['Name', 'Q1', 'Q2', 'Q3']):
    table.cell(0, i).text = header
```
