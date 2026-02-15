---
name: excel-processing
description: "Excel file processing with validation and transformation. Use when importing or exporting Excel data."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Excel Processing

## Reading Excel Files
```typescript
import * as XLSX from 'xlsx';

function readExcel(filePath: string) {
  const workbook = XLSX.readFile(filePath);
  const sheetName = workbook.SheetNames[0];
  const sheet = workbook.Sheets[sheetName];
  return XLSX.utils.sheet_to_json(sheet);
}
```

## Writing Excel Files
```typescript
function writeExcel(data: any[], filePath: string) {
  const worksheet = XLSX.utils.json_to_sheet(data);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, 'Data');
  XLSX.writeFile(workbook, filePath);
}
```

## Column Mapping
```typescript
const columnMap = {
  'Provider Name': 'name',
  'NPI Number': 'npi',
  'Tax ID': 'tin',
  'Address': 'address'
};

function mapColumns(row: Record<string, any>) {
  return Object.entries(columnMap).reduce((acc, [excel, db]) => {
    acc[db] = row[excel];
    return acc;
  }, {});
}
```

## Validation
```typescript
function validateRow(row: any, index: number): ValidationError[] {
  const errors = [];
  
  if (!row.npi || !validateNPI(row.npi)) {
    errors.push({ row: index, field: 'npi', message: 'Invalid NPI' });
  }
  
  return errors;
}
```

## Batch Processing
```typescript
const BATCH_SIZE = 1000;

for (let i = 0; i < rows.length; i += BATCH_SIZE) {
  const batch = rows.slice(i, i + BATCH_SIZE);
  await processBatch(batch);
}
```
