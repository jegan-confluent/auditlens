---
name: cost-report
description: API cost report
---
# Cost Report
```bash
cat logs/tokens-$(date +%Y-%m-%d).jsonl | jq -s 'map(.cost) | add'
./tools/analyze-costs.sh
```
