---
name: expense-categorization
description: "Automatic expense categorization using rules and ML. Use when building expense tracking features."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Expense Categorization

## Rule-Based Categorization
```typescript
const MERCHANT_RULES = {
  'swiggy|zomato|uber eats': 'food_delivery',
  'amazon|flipkart|myntra': 'shopping',
  'ola|uber|rapido': 'transport',
  'netflix|hotstar|prime': 'entertainment',
  'airtel|jio|vodafone': 'utilities',
  'apollo|medplus|1mg': 'medical',
  'bigbasket|grofers|dmart': 'groceries'
};

function categorizeByMerchant(merchant: string): string | null {
  for (const [pattern, category] of Object.entries(MERCHANT_RULES)) {
    if (new RegExp(pattern, 'i').test(merchant)) {
      return category;
    }
  }
  return null;
}
```

## Amount-Based Hints
```typescript
function getCategoryHints(amount: number): string[] {
  if (amount < 100) return ['snacks', 'transport', 'misc'];
  if (amount < 500) return ['groceries', 'food', 'utilities'];
  if (amount < 2000) return ['shopping', 'medical', 'bills'];
  return ['rent', 'emi', 'major_purchase'];
}
```

## Learning from History
```typescript
async function suggestCategory(transaction: Transaction) {
  // 1. Try exact merchant match
  const byMerchant = categorizeByMerchant(transaction.merchant);
  if (byMerchant) return { category: byMerchant, confidence: 0.95 };
  
  // 2. Check user's history for similar transactions
  const similar = await findSimilarTransactions(transaction);
  if (similar.length > 3) {
    const mostCommon = mode(similar.map(t => t.category));
    return { category: mostCommon, confidence: 0.8 };
  }
  
  // 3. Fall back to amount-based suggestion
  return { category: getCategoryHints(transaction.amount)[0], confidence: 0.5 };
}
```
