#!/bin/bash
[ -z "$1" ] && echo "Usage: ./tools/setup-project.sh /path/to/project" && exit 1
echo "📦 Setting up: $1"
echo "Copy master setup script and run it in the target project"
