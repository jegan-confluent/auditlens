---
name: healthcare-validation
description: "Healthcare identifier validation including NPI, TIN, DEA numbers. Use when validating provider data."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Healthcare Validation

## NPI Validation (Luhn Algorithm)
```typescript
function validateNPI(npi: string): boolean {
  if (!/^\d{10}$/.test(npi)) return false;
  
  const digits = ('80840' + npi).split('').map(Number);
  let sum = 0;
  
  for (let i = digits.length - 1; i >= 0; i--) {
    let digit = digits[i];
    if ((digits.length - i) % 2 === 0) {
      digit *= 2;
      if (digit > 9) digit -= 9;
    }
    sum += digit;
  }
  
  return sum % 10 === 0;
}
```

## TIN Validation
```typescript
function validateTIN(tin: string): boolean {
  // Remove dashes
  const clean = tin.replace(/-/g, '');
  return /^\d{9}$/.test(clean);
}
```

## DEA Number Validation
```typescript
function validateDEA(dea: string): boolean {
  if (!/^[A-Z]{2}\d{7}$/.test(dea)) return false;
  
  const digits = dea.slice(2).split('').map(Number);
  const sum1 = digits[0] + digits[2] + digits[4];
  const sum2 = (digits[1] + digits[3] + digits[5]) * 2;
  
  return (sum1 + sum2) % 10 === digits[6];
}
```

## Common Healthcare Identifiers
| ID | Format | Example |
|----|--------|---------|
| NPI | 10 digits | 1234567893 |
| TIN | 9 digits | 12-3456789 |
| DEA | 2 letters + 7 digits | AB1234563 |
| Medicare | 11 chars | 1EG4-TE5-MK72 |
