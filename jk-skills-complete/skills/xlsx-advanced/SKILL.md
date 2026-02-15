---
name: xlsx-advanced
description: "Advanced Excel operations with formulas, charts, and formatting. Use when creating complex spreadsheets."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Advanced Excel Operations

## Using openpyxl
```python
from openpyxl import Workbook
from openpyxl.styles import Font, Fill, Alignment, Border
from openpyxl.chart import BarChart, Reference

wb = Workbook()
ws = wb.active
ws.title = "Sales Data"

# Headers with styling
headers = ['Product', 'Q1', 'Q2', 'Q3', 'Q4', 'Total']
for col, header in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=header)
    cell.font = Font(bold=True)
    cell.alignment = Alignment(horizontal='center')

# Data with formulas
data = [
    ['Product A', 100, 150, 200, 180],
    ['Product B', 200, 220, 180, 250],
]

for row_num, row_data in enumerate(data, 2):
    for col_num, value in enumerate(row_data, 1):
        ws.cell(row=row_num, column=col_num, value=value)
    # Sum formula
    ws.cell(row=row_num, column=6, value=f'=SUM(B{row_num}:E{row_num})')

wb.save('output.xlsx')
```

## Charts
```python
chart = BarChart()
chart.title = "Quarterly Sales"
chart.x_axis.title = "Quarter"
chart.y_axis.title = "Revenue"

data = Reference(ws, min_col=2, max_col=5, min_row=1, max_row=3)
categories = Reference(ws, min_col=1, min_row=2, max_row=3)
chart.add_data(data, titles_from_data=True)
chart.set_categories(categories)

ws.add_chart(chart, "H2")
```

## Conditional Formatting
```python
from openpyxl.formatting.rule import ColorScaleRule

ws.conditional_formatting.add('B2:E10',
    ColorScaleRule(
        start_type='min', start_color='FF0000',
        mid_type='percentile', mid_value=50, mid_color='FFFF00',
        end_type='max', end_color='00FF00'
    )
)
```
