---
name: docx-advanced
description: "Advanced Word document creation with styles, tables, and images. Use when generating professional documents."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Advanced DOCX Generation

## Using python-docx
```python
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# Title
title = doc.add_heading('Report Title', 0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER

# Paragraph with formatting
para = doc.add_paragraph()
run = para.add_run('Bold and ')
run.bold = True
run = para.add_run('italic text')
run.italic = True

# Table
table = doc.add_table(rows=3, cols=3)
table.style = 'Table Grid'
for i, row in enumerate(table.rows):
    for j, cell in enumerate(row.cells):
        cell.text = f'Row {i}, Col {j}'

# Image
doc.add_picture('image.png', width=Inches(4))

doc.save('output.docx')
```

## Template-Based Generation
```python
from docxtpl import DocxTemplate

doc = DocxTemplate("template.docx")
context = {
    'company_name': 'Acme Corp',
    'date': '2024-01-15',
    'items': [
        {'name': 'Item 1', 'price': 100},
        {'name': 'Item 2', 'price': 200}
    ]
}
doc.render(context)
doc.save("generated.docx")
```

## Styles
```python
from docx.enum.style import WD_STYLE_TYPE

# Custom style
styles = doc.styles
style = styles.add_style('CustomHeading', WD_STYLE_TYPE.PARAGRAPH)
style.font.size = Pt(14)
style.font.bold = True
```
