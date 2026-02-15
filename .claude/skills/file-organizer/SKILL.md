---
name: file-organizer
description: Intelligently organize files and folders
---
# File Organizer

## Overview
Intelligently organizes files and folders across your computer.

## Organization Patterns
```
Downloads/
├── Documents/
│   ├── PDFs/
│   ├── Spreadsheets/
│   └── Presentations/
├── Images/
│   ├── Screenshots/
│   └── Photos/
├── Code/
│   └── [by language]
└── Archives/
    └── [by date]
```

## Usage
```
Organize my Downloads folder by file type
Sort these files by date
Move old files to archive
```

## Script Pattern
```bash
# Organize by extension
for ext in pdf docx xlsx png jpg; do
  mkdir -p "$ext"
  mv *.$ext "$ext/" 2>/dev/null
done
```
