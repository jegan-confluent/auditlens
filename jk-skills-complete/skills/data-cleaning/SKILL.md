---
name: data-cleaning
description: "Data cleaning and normalization patterns. Use when preparing messy data for processing."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Data Cleaning

## String Normalization
```typescript
function normalizeString(input: string): string {
  return input
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .normalize('NFKD');
}

function normalizePhone(phone: string): string {
  return phone.replace(/\D/g, '').slice(-10);
}

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}
```

## Address Standardization
```typescript
const abbreviations = {
  'street': 'ST', 'avenue': 'AVE', 'boulevard': 'BLVD',
  'drive': 'DR', 'road': 'RD', 'lane': 'LN'
};

function standardizeAddress(address: string): string {
  let result = address.toUpperCase();
  for (const [full, abbr] of Object.entries(abbreviations)) {
    result = result.replace(new RegExp(full, 'gi'), abbr);
  }
  return result;
}
```

## Deduplication
```typescript
function findDuplicates(records: any[], keys: string[]) {
  const seen = new Map();
  const duplicates = [];
  
  for (const record of records) {
    const key = keys.map(k => record[k]).join('|');
    if (seen.has(key)) {
      duplicates.push({ original: seen.get(key), duplicate: record });
    } else {
      seen.set(key, record);
    }
  }
  
  return duplicates;
}
```

## Null Handling
```typescript
function cleanNulls(obj: any): any {
  return Object.fromEntries(
    Object.entries(obj)
      .filter(([_, v]) => v != null && v !== '')
      .map(([k, v]) => [k, typeof v === 'string' ? v.trim() : v])
  );
}
```
