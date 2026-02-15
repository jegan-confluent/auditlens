---
name: pdf-processing
description: "PDF creation, manipulation, and text extraction. Use when working with PDF files."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# PDF Processing

## Create PDF with ReportLab
```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

c = canvas.Canvas("output.pdf", pagesize=letter)
width, height = letter

# Text
c.setFont("Helvetica-Bold", 16)
c.drawString(1*inch, height - 1*inch, "Document Title")

c.setFont("Helvetica", 12)
c.drawString(1*inch, height - 1.5*inch, "Regular paragraph text here.")

# Table
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

data = [['Name', 'Age'], ['John', '30'], ['Jane', '25']]
table = Table(data)
table.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('GRID', (0, 0), (-1, -1), 1, colors.black)
]))

c.save()
```

## Extract Text with PyMuPDF
```python
import fitz  # PyMuPDF

doc = fitz.open("input.pdf")
text = ""
for page in doc:
    text += page.get_text()

# Extract images
for page_num, page in enumerate(doc):
    for img_index, img in enumerate(page.get_images()):
        xref = img[0]
        base = doc.extract_image(xref)
        image_bytes = base["image"]
```

## Merge PDFs
```python
from PyPDF2 import PdfMerger

merger = PdfMerger()
merger.append("file1.pdf")
merger.append("file2.pdf")
merger.write("merged.pdf")
merger.close()
```

## Fill PDF Forms
```python
from PyPDF2 import PdfReader, PdfWriter

reader = PdfReader("form.pdf")
writer = PdfWriter()

writer.append(reader)
writer.update_page_form_field_values(
    writer.pages[0],
    {"field_name": "field_value"}
)
writer.write("filled.pdf")
```
