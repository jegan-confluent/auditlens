---
name: xero-integration
description: "Xero accounting integration for invoicing and payments. Use when integrating with Xero API."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Xero Integration

## OAuth2 Setup
```typescript
const xeroClient = new XeroClient({
  clientId: process.env.XERO_CLIENT_ID,
  clientSecret: process.env.XERO_CLIENT_SECRET,
  redirectUris: [process.env.XERO_REDIRECT_URI],
  scopes: ['openid', 'profile', 'email', 'accounting.transactions']
});
```

## Create Invoice
```typescript
async function createInvoice(tenantId: string, invoice: InvoiceData) {
  const invoices = {
    invoices: [{
      type: Invoice.TypeEnum.ACCREC,
      contact: { contactID: invoice.contactId },
      lineItems: invoice.items.map(item => ({
        description: item.description,
        quantity: item.quantity,
        unitAmount: item.unitPrice,
        accountCode: '200'
      })),
      date: new Date().toISOString().split('T')[0],
      dueDate: addDays(new Date(), 30).toISOString().split('T')[0],
      reference: invoice.reference
    }]
  };
  
  return xeroClient.accountingApi.createInvoices(tenantId, invoices);
}
```

## Get Contacts
```typescript
async function getContacts(tenantId: string) {
  const response = await xeroClient.accountingApi.getContacts(tenantId);
  return response.body.contacts;
}
```

## Webhook Handler
```typescript
app.post('/webhooks/xero', (req, res) => {
  const signature = req.headers['x-xero-signature'];
  if (!verifyWebhook(req.body, signature)) {
    return res.status(401).send();
  }
  
  // Process event
  const event = req.body.events[0];
  if (event.eventType === 'INVOICE.PAID') {
    handleInvoicePaid(event.resourceId);
  }
  
  res.status(200).send();
});
```
