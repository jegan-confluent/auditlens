#!/bin/bash
#===============================================================================
# JK Claude Skills v4.0 - Complete Installation Script
# 66 Skills for Claude Code
#===============================================================================

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     JK Claude Skills v4.0 - Complete Package (66 Skills)      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${HOME}/.claude/skills"

# Create directories
mkdir -p "$SKILLS_DIR"
mkdir -p "${HOME}/.claude/hooks"
mkdir -p "${HOME}/.claude/logs"

# Copy all skills
echo "Installing 66 skills..."
cp -r "$SCRIPT_DIR/skills/"* "$SKILLS_DIR/"

# Count installed
INSTALLED=$(ls -1 "$SKILLS_DIR" | wc -l)

echo ""
echo -e "${GREEN}✅ Installation Complete!${NC}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Skills installed: $INSTALLED"
echo "  Location: $SKILLS_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Categories:"
echo "  • Core Development (12)"
echo "  • Healthcare (6)"
echo "  • Patient Portal (6)"
echo "  • Fintech (4)"
echo "  • EdTech (3)"
echo "  • ML/HuggingFace (4)"
echo "  • Workflow (6)"
echo "  • Documents (5)"
echo "  • DevOps (6)"
echo "  • Screen/Browser (2)"
echo "  • Analysis (4)"
echo "  • Creative (4)"
echo "  • Security (4)"
echo ""
echo "Next steps:"
echo "  1. Start Claude Code: claude"
echo "  2. Try: 'Create a TypeScript interface'"
echo ""
echo "For dev-browser (screen watching):"
echo "  1. Install Bun: curl -fsSL https://bun.sh/install | bash"
echo "  2. In Claude Code: /plugin marketplace add sawyerhood/dev-browser"
echo "  3. In Claude Code: /plugin install dev-browser@sawyerhood/dev-browser"
echo ""
