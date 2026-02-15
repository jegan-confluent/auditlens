"""Metric card components"""

def render_metric_card(label, value, color="purple"):
    # Format numeric values with commas, leave strings as-is
    if isinstance(value, (int, float)):
        formatted_value = f"{value:,}"
    else:
        formatted_value = str(value)

    return f'''
    <div class="metric-card {color}">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{formatted_value}</div>
    </div>
    '''
