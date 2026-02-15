---
name: csv-data-summarizer
description: Automatically analyze CSV files
---
# CSV Data Summarizer

## Overview
Automatically analyzes CSVs: columns, distributions, missing data, correlations.

## Analysis Output
```
Column Analysis:
- name: string (100% complete)
- age: numeric (mean: 34.5, std: 12.3, 2% missing)
- email: string (unique: 98%, 0% missing)

Correlations:
- age ↔ income: 0.72 (strong positive)

Missing Data:
- phone: 15% missing
- address: 8% missing
```

## Usage
```
Analyze this CSV and summarize the data quality
What columns have the most missing values?
Show me the distribution of the 'status' column
```

## Code Pattern
```python
import pandas as pd
df = pd.read_csv('data.csv')
print(df.describe())
print(df.isnull().sum())
print(df.dtypes)
```
