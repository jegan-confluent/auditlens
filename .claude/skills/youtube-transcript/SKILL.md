---
name: youtube-transcript
description: Fetch and summarize YouTube video transcripts
---
# YouTube Transcript

## Overview
Fetch transcripts from YouTube videos for summarization and analysis.

## Usage
```
Get the transcript from this YouTube video: [URL]
Summarize the key points from this video
Extract action items from this tutorial
```

## Tools
```bash
# yt-dlp for transcripts
yt-dlp --write-auto-sub --sub-lang en --skip-download [URL]

# Or use API
youtube-transcript-api [VIDEO_ID]
```

## Output Format
```
[00:00] Introduction
[02:30] Key Point 1
[05:45] Key Point 2
[10:00] Conclusion

Summary: [Brief overview]
Key Takeaways:
1. [Point 1]
2. [Point 2]
```
