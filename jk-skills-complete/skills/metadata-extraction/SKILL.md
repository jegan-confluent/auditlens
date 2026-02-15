---
name: metadata-extraction
description: "Extract metadata from files and documents. Use for OSINT and document analysis."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Metadata Extraction

## ExifTool (Universal)
```bash
# View all metadata
exiftool document.pdf

# Specific fields
exiftool -Author -CreateDate -ModifyDate document.docx

# Recursive directory
exiftool -r -json /path/to/files > metadata.json

# Remove metadata
exiftool -all= sensitive.jpg
```

## Image Metadata
```bash
# GPS coordinates
exiftool -gpslatitude -gpslongitude image.jpg

# Camera info
exiftool -make -model -datetime image.jpg

# All EXIF
exiftool -EXIF:all image.jpg
```

## PDF Metadata
```bash
# Using pdfinfo
pdfinfo document.pdf

# Using exiftool
exiftool -Creator -Producer -CreateDate -ModifyDate document.pdf
```

## Document Properties
```bash
# Office documents
exiftool -Author -LastModifiedBy -Company -CreateDate file.docx

# Extract embedded files
binwalk -e document.docx
```

## Python Extraction
```python
from PIL import Image
from PIL.ExifTags import TAGS

img = Image.open('image.jpg')
exif = img._getexif()

for tag_id, value in exif.items():
    tag = TAGS.get(tag_id, tag_id)
    print(f"{tag}: {value}")
```

## OSINT Use Cases
- Identify document author
- Find creation location (GPS)
- Determine software used
- Track document history
