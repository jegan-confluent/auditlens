---
name: computer-forensics
description: "Digital forensics techniques for incident investigation. Use when analyzing compromised systems."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Computer Forensics

## Evidence Collection Order (Volatility)
1. Registers, cache
2. Memory (RAM)
3. Network state
4. Running processes
5. Disk
6. Backups

## Memory Acquisition
```bash
# Linux
sudo dd if=/dev/mem of=memory.dump

# Using LiME
sudo insmod lime.ko "path=/tmp/memory.lime format=lime"

# Volatility 3 analysis
vol3 -f memory.dump windows.pslist
vol3 -f memory.dump windows.netscan
vol3 -f memory.dump windows.malfind
```

## Disk Forensics
```bash
# Create forensic image
sudo dd if=/dev/sda of=disk.img bs=4M status=progress

# Mount read-only
sudo mount -o ro,loop disk.img /mnt/evidence

# File carving
foremost -t all -i disk.img -o carved_files

# Deleted files
sudo fls -r -d disk.img
```

## Timeline Analysis
```bash
# Create timeline
fls -r -m / disk.img > bodyfile.txt
mactime -b bodyfile.txt -d > timeline.csv
```

## Hashing for Integrity
```bash
# Generate hashes
sha256sum disk.img > disk.sha256
md5sum disk.img > disk.md5

# Verify
sha256sum -c disk.sha256
```

## Chain of Custody
- Document who handled evidence
- Record all timestamps
- Use write blockers for disk analysis
- Photograph physical evidence
