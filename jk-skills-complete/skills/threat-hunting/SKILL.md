---
name: threat-hunting
description: "Security threat hunting patterns and techniques. Use when investigating security incidents."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Threat Hunting

## Investigation Framework
1. **Hypothesis**: Define what you're looking for
2. **Data Collection**: Gather logs and artifacts
3. **Analysis**: Look for anomalies
4. **Findings**: Document discoveries
5. **Response**: Take action

## Common Indicators of Compromise (IoCs)
```bash
# Unusual outbound connections
netstat -tuln | grep ESTABLISHED

# Recent file modifications
find /var/www -mtime -1 -type f

# Failed login attempts
grep "Failed password" /var/log/auth.log | tail -50

# Suspicious processes
ps aux | grep -E "(nc|ncat|netcat|wget|curl)" | grep -v grep

# Cron jobs
crontab -l
cat /etc/crontab
ls -la /etc/cron.*
```

## Log Analysis
```bash
# Apache access log anomalies
cat access.log | awk '{print $1}' | sort | uniq -c | sort -rn | head -20

# 404 hunting (directory scanning)
grep " 404 " access.log | awk '{print $7}' | sort | uniq -c | sort -rn

# SQL injection attempts
grep -E "(union|select|from|where|drop|insert)" access.log

# Shell command injection
grep -E "(%3B|;|%7C|\||%26|&)" access.log
```

## YARA Rules
```yara
rule WebShell {
    strings:
        $php1 = "eval($_" ascii
        $php2 = "base64_decode" ascii
        $php3 = "shell_exec" ascii
    condition:
        2 of them
}
```

## Network Analysis
```bash
# Capture traffic
tcpdump -i eth0 -w capture.pcap

# Analyze with tshark
tshark -r capture.pcap -Y "http.request" -T fields -e ip.src -e http.host
```
