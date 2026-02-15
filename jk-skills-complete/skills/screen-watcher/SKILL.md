---
name: screen-watcher
description: "Capture and analyze your screen without manual screenshots. Use when you need Claude to see your desktop, IDE, terminal, or any non-browser application. Enables pair programming where Claude watches your screen."
allowed-tools: "Bash,Read,Write"
version: 1.0.0
---

# Screen Watcher

Capture your screen so Claude can see what you're working on - no manual screenshots needed.

## When to Use This Skill

- Pair programming where Claude needs to see your IDE
- Debugging issues visible on screen
- When you say "look at this" or "can you see..."
- Reviewing UI/design of desktop apps
- Any time Claude needs visual context of your work

## Quick Capture Methods

### Method 1: macOS Screenshot (Simplest)
```bash
# Capture full screen to file
screencapture -x /tmp/screen.png

# Capture and copy to clipboard
screencapture -c

# Capture specific window (interactive)
screencapture -w /tmp/window.png
```

### Method 2: Linux (ImageMagick)
```bash
# Install if needed
sudo apt install imagemagick

# Capture full screen
import -window root /tmp/screen.png

# Capture active window
import -window "$(xdotool getactivewindow)" /tmp/window.png
```

### Method 3: Cross-Platform (scrot/maim)
```bash
# Linux with scrot
scrot /tmp/screen.png

# Linux with maim (better)
maim /tmp/screen.png
maim -s /tmp/selection.png  # Select area
```

## Automated Screen Watching

### Periodic Capture Script
```bash
#!/bin/bash
# watch-screen.sh - Capture screen every N seconds

INTERVAL=${1:-5}  # Default 5 seconds
OUTPUT_DIR="/tmp/screen-watch"
mkdir -p "$OUTPUT_DIR"

echo "Watching screen every ${INTERVAL}s. Ctrl+C to stop."

while true; do
  TIMESTAMP=$(date +%Y%m%d_%H%M%S)
  screencapture -x "$OUTPUT_DIR/screen_$TIMESTAMP.png" 2>/dev/null || \
  import -window root "$OUTPUT_DIR/screen_$TIMESTAMP.png" 2>/dev/null
  
  # Keep only last 10 captures
  ls -t "$OUTPUT_DIR"/*.png | tail -n +11 | xargs rm -f 2>/dev/null
  
  sleep "$INTERVAL"
done
```

### Usage with Claude
```bash
# Start watching
./watch-screen.sh 10 &

# Ask Claude to check latest
"Look at /tmp/screen-watch/ and tell me what you see"
```

## On-Demand Capture for Claude

### Create a Quick Capture Alias
Add to `~/.bashrc` or `~/.zshrc`:
```bash
alias snap='screencapture -x /tmp/claude-screen.png && echo "Captured to /tmp/claude-screen.png"'
```

Then just type `snap` before asking Claude to look.

## Workflow: Pair Programming with Claude

1. **Start your work** in IDE/terminal
2. **Capture when stuck:**
   ```bash
   snap  # or screencapture -x /tmp/screen.png
   ```
3. **Ask Claude:**
   ```
   "Look at /tmp/claude-screen.png - I'm getting an error, what's wrong?"
   ```
4. **Claude analyzes** the screenshot and helps debug

## Advanced: Continuous Monitoring

### Using fswatch (macOS)
```bash
# Watch for file changes and capture
brew install fswatch
fswatch -o ~/myproject | while read; do
  screencapture -x /tmp/project-screen.png
done
```

### Using Screenpipe (AI-native)
For full AI-powered screen recording and analysis:
```bash
# Install Screenpipe
brew install screenpipe

# Run with local AI
screenpipe --local
```
See: https://github.com/mediar-ai/screenpipe

## Tips

- **Reduce image size** for faster processing:
  ```bash
  screencapture -x -t jpg -T 0 /tmp/screen.jpg
  ```

- **Capture specific coordinates:**
  ```bash
  screencapture -R 0,0,800,600 /tmp/region.png
  ```

- **Exclude sensitive areas** by capturing specific windows only

## Combining with Dev Browser

- Use **Dev Browser** for web apps (more efficient)
- Use **Screen Watcher** for:
  - IDEs (VS Code, Cursor)
  - Terminal/console output
  - Desktop applications
  - System dialogs
  - Anything not in a browser
