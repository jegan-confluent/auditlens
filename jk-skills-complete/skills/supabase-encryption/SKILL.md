---
name: supabase-encryption
description: "Field-level encryption for Supabase using RPC functions. Use when storing sensitive data."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Supabase Encryption

## Setup pgcrypto
```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

## Encryption Functions
```sql
-- Encrypt function
CREATE OR REPLACE FUNCTION encrypt_field(data TEXT, key TEXT)
RETURNS TEXT AS $$
BEGIN
  RETURN encode(
    pgp_sym_encrypt(data, key),
    'base64'
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Decrypt function
CREATE OR REPLACE FUNCTION decrypt_field(encrypted TEXT, key TEXT)
RETURNS TEXT AS $$
BEGIN
  RETURN pgp_sym_decrypt(
    decode(encrypted, 'base64'),
    key
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

## Usage in Application
```typescript
// Store encrypted
const { data, error } = await supabase.rpc('encrypt_field', {
  data: sensitiveValue,
  key: process.env.ENCRYPTION_KEY
});

// Retrieve decrypted
const { data, error } = await supabase.rpc('decrypt_field', {
  encrypted: encryptedValue,
  key: process.env.ENCRYPTION_KEY
});
```

## Column-Level Encryption
```sql
CREATE TABLE patients (
  id UUID PRIMARY KEY,
  name TEXT,  -- Not encrypted
  ssn_encrypted TEXT,  -- Encrypted
  dob_encrypted TEXT   -- Encrypted
);

-- Insert with encryption
INSERT INTO patients (id, name, ssn_encrypted)
VALUES (
  gen_random_uuid(),
  'John Doe',
  encrypt_field('123-45-6789', current_setting('app.encryption_key'))
);
```

## Key Management
- Store key in environment variable
- Rotate keys periodically
- Never log or expose keys
