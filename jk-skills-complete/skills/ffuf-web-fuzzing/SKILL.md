---
name: ffuf-web-fuzzing
description: "Web fuzzing with ffuf for security testing. Use when discovering hidden endpoints."
allowed-tools: "Bash,Read,Write"
version: 1.0.0
---

# FFUF Web Fuzzing

## Basic Usage
```bash
# Directory discovery
ffuf -u https://example.com/FUZZ -w /usr/share/wordlists/dirb/common.txt

# With extensions
ffuf -u https://example.com/FUZZ -w wordlist.txt -e .php,.html,.txt

# Filter by status code
ffuf -u https://example.com/FUZZ -w wordlist.txt -fc 404,403
```

## Parameter Fuzzing
```bash
# GET parameter
ffuf -u "https://example.com/api?FUZZ=test" -w params.txt

# POST data
ffuf -u https://example.com/login -X POST -d "user=admin&FUZZ=test" -w wordlist.txt

# JSON body
ffuf -u https://example.com/api -X POST -H "Content-Type: application/json" \
  -d '{"FUZZ":"test"}' -w wordlist.txt
```

## Virtual Host Discovery
```bash
ffuf -u https://example.com -H "Host: FUZZ.example.com" -w subdomains.txt
```

## Advanced Options
```bash
# Rate limiting
ffuf -u https://example.com/FUZZ -w wordlist.txt -rate 100

# Threads
ffuf -u https://example.com/FUZZ -w wordlist.txt -t 50

# Output formats
ffuf -u https://example.com/FUZZ -w wordlist.txt -o results.json -of json

# Filter by response size
ffuf -u https://example.com/FUZZ -w wordlist.txt -fs 1234

# Filter by word count
ffuf -u https://example.com/FUZZ -w wordlist.txt -fw 100
```

## Wordlists
- SecLists: https://github.com/danielmiessler/SecLists
- Common: `/usr/share/wordlists/dirb/common.txt`
- Big: `/usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt`
