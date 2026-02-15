---
name: hipaa-compliance
description: "HIPAA compliance patterns for handling PHI. Use when building healthcare applications."
allowed-tools: "Read,Write"
version: 1.0.0
---

# HIPAA Compliance

## Protected Health Information (PHI)
These 18 identifiers are PHI:
1. Names
2. Geographic data (smaller than state)
3. Dates (except year)
4. Phone numbers
5. Fax numbers
6. Email addresses
7. SSN
8. Medical record numbers
9. Health plan numbers
10. Account numbers
11. Certificate/license numbers
12. Vehicle identifiers
13. Device identifiers
14. URLs
15. IP addresses
16. Biometric identifiers
17. Photos
18. Any unique identifier

## Code Patterns
```typescript
// ❌ NEVER log PHI
console.log(patient.ssn); // VIOLATION!

// ✅ Use redaction
console.log(redactPHI(patient));

// ❌ NEVER in URLs
/api/patients/john-doe-ssn-123456789

// ✅ Use opaque IDs
/api/patients/uuid-here
```

## Encryption Requirements
- Encrypt PHI at rest (AES-256)
- Encrypt PHI in transit (TLS 1.2+)
- Encrypt database fields containing PHI

## Access Controls
- Minimum necessary access
- Role-based permissions
- Audit logging required
- Automatic session timeout

## Audit Logging
```typescript
await auditLog({
  userId: user.id,
  action: 'VIEW_PATIENT',
  resourceId: patient.id,
  timestamp: new Date(),
  ipAddress: req.ip
});
```
