---
name: financial-security
description: "Financial data security including PCI-DSS patterns and secure storage. Use when handling financial data."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Financial Security

## Card Data Handling (PCI-DSS)
```typescript
// NEVER store full card numbers
// NEVER log card details

// Mask card number for display
function maskCardNumber(cardNumber: string): string {
  return '**** **** **** ' + cardNumber.slice(-4);
}

// Store only last 4 digits
interface StoredCard {
  id: string;
  last4: string;
  brand: string;
  expiryMonth: number;
  expiryYear: number;
  tokenizedId: string;  // From payment processor
}
```

## Tokenization
```typescript
// Use payment processor tokens instead of raw card data
async function saveCard(userId: string, token: string) {
  // Token from Stripe/Razorpay - never raw card
  const paymentMethod = await stripe.paymentMethods.retrieve(token);
  
  await db.insert(userCards).values({
    userId,
    stripePaymentMethodId: paymentMethod.id,
    last4: paymentMethod.card.last4,
    brand: paymentMethod.card.brand
  });
}
```

## Transaction Security
```typescript
// Rate limiting
const RATE_LIMITS = {
  transactionsPerMinute: 10,
  amountPerDay: 100000,  // In paise
  failedAttemptsBeforeLock: 3
};

// Velocity checks
async function checkVelocity(userId: string, amount: number) {
  const recentTxns = await getRecentTransactions(userId, '24h');
  const totalAmount = recentTxns.reduce((sum, tx) => sum + tx.amount, 0);
  
  if (totalAmount + amount > RATE_LIMITS.amountPerDay) {
    throw new Error('Daily limit exceeded');
  }
}
```

## Audit Trail
```typescript
// Log all financial operations
await auditLog.create({
  type: 'TRANSACTION',
  userId,
  action: 'CREATE',
  amount,
  ipAddress: req.ip,
  userAgent: req.headers['user-agent'],
  timestamp: new Date()
});
```
