---
name: patient-intake
description: "Patient intake workflows including forms, QR codes, and document collection. Use for patient onboarding."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Patient Intake

## QR Code Check-In
```typescript
import QRCode from 'qrcode';

async function generateCheckinQR(appointmentId: string) {
  const url = `${BASE_URL}/checkin/${appointmentId}`;
  return QRCode.toDataURL(url);
}
```

## Form Schema
```typescript
const intakeFormSchema = z.object({
  personalInfo: z.object({
    firstName: z.string().min(1),
    lastName: z.string().min(1),
    dateOfBirth: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    medicare: z.string().optional()
  }),
  medicalHistory: z.object({
    conditions: z.array(z.string()),
    medications: z.array(z.object({
      name: z.string(),
      dosage: z.string()
    })),
    allergies: z.array(z.string())
  }),
  consent: z.object({
    privacyPolicy: z.literal(true),
    treatmentConsent: z.literal(true)
  })
});
```

## Document Upload
```typescript
const ALLOWED_TYPES = ['application/pdf', 'image/jpeg', 'image/png'];
const MAX_SIZE = 10 * 1024 * 1024; // 10MB

function validateDocument(file: File): boolean {
  return ALLOWED_TYPES.includes(file.type) && file.size <= MAX_SIZE;
}
```

## Workflow Steps
1. Patient scans QR code
2. Verify identity (DOB + Medicare)
3. Complete intake form
4. Upload documents (ID, insurance)
5. Sign consent forms
6. Notify reception
