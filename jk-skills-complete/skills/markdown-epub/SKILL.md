---
name: markdown-epub
description: "Convert Markdown to EPUB ebooks. Use when creating ebooks from markdown content."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Markdown to EPUB

## Using Pandoc
```bash
# Basic conversion
pandoc input.md -o output.epub

# With metadata
pandoc input.md -o output.epub \
  --metadata title="Book Title" \
  --metadata author="Author Name" \
  --epub-cover-image=cover.jpg

# With CSS styling
pandoc input.md -o output.epub --css=style.css

# Multiple files
pandoc chapter1.md chapter2.md chapter3.md -o book.epub
```

## Metadata YAML
```yaml
---
title: My Book
author: John Doe
date: 2024-01-15
lang: en
cover-image: cover.jpg
description: A book about something
---
```

## Using Python (ebooklib)
```python
from ebooklib import epub

book = epub.EpubBook()

# Metadata
book.set_identifier('id123')
book.set_title('My Book')
book.set_language('en')
book.add_author('Author Name')

# Chapter
c1 = epub.EpubHtml(title='Chapter 1', file_name='chap_01.xhtml', lang='en')
c1.content = '<h1>Chapter 1</h1><p>Content here...</p>'
book.add_item(c1)

# TOC and spine
book.toc = [epub.Link('chap_01.xhtml', 'Chapter 1', 'chap1')]
book.spine = ['nav', c1]

# Required items
book.add_item(epub.EpubNcx())
book.add_item(epub.EpubNav())

epub.write_epub('book.epub', book)
```

## CSS for EPUB
```css
body { font-family: Georgia, serif; line-height: 1.6; }
h1 { text-align: center; margin-top: 2em; }
p { text-indent: 1.5em; margin: 0; }
```
