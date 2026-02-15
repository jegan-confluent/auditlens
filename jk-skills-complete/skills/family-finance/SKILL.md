---
name: family-finance
description: "Family finance patterns with Indian cultural context including festivals, UPI, and joint expenses. Use for CashKoda."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Family Finance (Indian Context)

## Festival Budget Planning
```typescript
const INDIAN_FESTIVALS = {
  diwali: { month: 10, duration: 5, typicalSpend: 'high' },
  holi: { month: 3, duration: 2, typicalSpend: 'medium' },
  durga_puja: { month: 10, duration: 9, typicalSpend: 'high' },
  eid: { month: 'lunar', duration: 3, typicalSpend: 'high' },
  onam: { month: 8, duration: 10, typicalSpend: 'medium' },
  pongal: { month: 1, duration: 4, typicalSpend: 'medium' }
};

function getUpcomingFestivals(region: string) {
  // Filter by regional relevance
  return Object.entries(INDIAN_FESTIVALS)
    .filter(([name, _]) => isRegionalFestival(name, region))
    .sort((a, b) => a[1].month - b[1].month);
}
```

## Family Member Roles
```typescript
interface FamilyMember {
  id: string;
  name: string;
  role: 'head' | 'spouse' | 'child' | 'parent' | 'other';
  canApprove: boolean;
  spendingLimit?: number;
}
```

## Expense Categories (Indian)
```typescript
const EXPENSE_CATEGORIES = [
  'groceries', 'vegetables', 'milk_dairy',
  'education_fees', 'tuition', 'school_supplies',
  'medical', 'medicines',
  'utilities', 'mobile_recharge', 'dth',
  'transport', 'petrol', 'auto_rickshaw',
  'household_help', 'rent', 'emi',
  'festivals', 'gifts', 'donations',
  'entertainment', 'dining_out'
];
```

## UPI Integration
```typescript
function generateUPILink(payment: Payment) {
  const params = new URLSearchParams({
    pa: payment.vpa,  // UPI ID
    pn: payment.payeeName,
    am: payment.amount.toString(),
    cu: 'INR',
    tn: payment.note
  });
  
  return `upi://pay?${params.toString()}`;
}
```

## Joint Expense Splitting
```typescript
function splitExpense(expense: Expense, members: FamilyMember[]) {
  const share = expense.amount / members.length;
  return members.map(m => ({
    memberId: m.id,
    amount: Math.round(share * 100) / 100
  }));
}
```
