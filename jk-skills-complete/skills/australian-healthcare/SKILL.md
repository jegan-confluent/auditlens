---
name: australian-healthcare
description: "Australian healthcare compliance including AHPRA, Medicare, and Privacy Act. Use for Australian healthcare apps."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Australian Healthcare

## AHPRA Registration Validation
```typescript
async function validateAHPRA(registrationNumber: string): Promise<boolean> {
  // Format: 3 letters + 10 digits (e.g., MED0001234567)
  if (!/^[A-Z]{3}\d{10}$/.test(registrationNumber)) {
    return false;
  }
  
  // Verify against AHPRA API
  const response = await fetch(
    `https://www.ahpra.gov.au/api/validate/${registrationNumber}`
  );
  return response.ok;
}
```

## Medicare Provider Number
```typescript
// Format: Location (4) + Provider (4) + Check (1)
function validateMedicareProvider(number: string): boolean {
  return /^\d{4}[A-Z]{2}\d{2}[A-Z]$/.test(number);
}
```

## Privacy Act 1988 Requirements
- Collect only necessary information
- Inform patients how data will be used
- Allow access and correction requests
- Secure storage and transmission
- Report data breaches within 72 hours

## Australian Privacy Principles (APPs)
1. Open and transparent management
2. Anonymity and pseudonymity
3. Collection of solicited information
4. Dealing with unsolicited information
5. Notification of collection
6. Use or disclosure
7. Direct marketing restrictions
8. Cross-border disclosure rules
9. Adoption of government identifiers
10. Quality of personal information
11. Security of personal information
12. Access to personal information
13. Correction of personal information

## My Health Record Integration
```typescript
// OAuth2 flow for My Health Record
const MHR_AUTH_URL = 'https://api.digitalhealth.gov.au/oauth2/authorize';
const MHR_TOKEN_URL = 'https://api.digitalhealth.gov.au/oauth2/token';
```
