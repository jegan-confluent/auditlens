 cmap='coolwarm')
plt.savefig('correlation.png')
```

## Generate Report
```python
def generate_report(df, output_path):
    report = f"""
# Data Analysis Report

## Overview
- Rows: {len(df)}
- Columns: {len(df.columns)}

## Column Details
{df.dtypes.to_markdown()}

## Statistics
{df.describe().to_markdown()}

## Missing Values
{df.isnull().sum().to_markdown()}
"""
    with open(output_path, 'w') as f:
        f.write(report)
```
