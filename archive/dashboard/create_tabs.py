#!/usr/bin/env python3
"""Generate all tab stub files"""

import re

# Read original app.py
with open('app.py.backup', 'r') as f:
    content = f.read()

# Extract all tab sections
tab_pattern = r'(with tab(\d+):.*?)'
matches = list(re.finditer(r'^with tab(\d+):\n((?:.*?\n)*?)(?=^with tab\d+:|^# =+|^if __name__|^\S+\s*=\s*st\.)', content, re.MULTILINE))

tab_names = [
    'audit_trail',
    'failures',
    'deletions',
    'api_keys',
    'security',
    'details',
    'analytics',
    'time_insights',
    'export',
    'security_alerts'
]

for i, (match, name) in enumerate(zip(matches, tab_names), 1):
    tab_num = match.group(1)
    tab_content = match.group(2)

    # Create module content
    module_content = f'''"""{ name.replace('_', ' ').title()} Tab"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from data.export import export_to_csv, export_to_json
from data.kafka_consumer import load_security_alerts


def render_tab(df, config=None):
    """Render the {name.replace('_', ' ').title()} tab"""
{tab_content}
'''

    # Write to file
    with open(f'tabs/{name}.py', 'w') as f:
        f.write(module_content)

    print(f"Created tabs/{name}.py")

print("All tab files created!")
