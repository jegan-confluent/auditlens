---
name: fintech-patterns
description: "Financial application patterns including transactions, reconciliation, and compliance. Use for fintech apps."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Fintech Patterns

## Transaction Processing
```typescript
interface Transaction {
  id: string;
  type: 'credit' | 'debit';
  amount: number;  // Store as cents/paise
  currency: string;
  status: 'pending' | 'completed' | 'failed';
  metadata: Record<string, any>;
}

// Always use integers for money
const amountInCents = Math.round(parseFloat(input) * 100);
```

## Double-Entry Bookkeeping
```typescript
async function recordTransaction(tx: Transaction) {
  await db.transaction(async (trx) => {
    // Debit source account
    await trx.insert(ledger).values({
      accountId: tx.sourceAccount,
      type: 'debit',
      amount: tx.amount
    });
    
    // Credit destination account
    await trx.insert(ledger).values({
      accountId: tx.destAccount,
      type: 'credit',
      amount: tx.amount
    });
  });
}
```

## Idempotency
```typescript
async function processPayment(idempotencyKey: string, payment: Payment) {
  // Check for existing transaction
  const existing = await db.query(
    'SELECT * FROM transactions WHERE idempotency_key = ?',
    [idempotencyKey]
  );
  
  if (existing) return existing;
  
  // Process new transaction
  return createTransaction({ ...payment, idempotencyKey });
}
```

## Currency Handling
```typescript
import Decimal from 'decimal.js';

function calculateTotal(items: LineItem[]): string {
  return items
    .reduce((sum, item) => sum.plus(item.amount), new Decimal(0))
    .toFixed(2);
}
```
