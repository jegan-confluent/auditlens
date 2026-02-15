---
name: article-extractor
description: Extract full article text and metadata from web pages
---
# Article Extractor

## Overview
Extract clean article text, metadata, and key information from web pages.

## Extracted Data
- Title
- Author
- Publication date
- Main content (cleaned)
- Images
- Related links

## Usage
```
Extract the article from this URL
Get the main content without ads/navigation
Summarize this news article
```

## Tools
```python
from newspaper import Article

article = Article(url)
article.download()
article.parse()

print(article.title)
print(article.text)
print(article.authors)
print(article.publish_date)
```
