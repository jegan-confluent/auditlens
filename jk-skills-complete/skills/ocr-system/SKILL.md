---
name: ocr-system
description: "OCR document processing with Azure Document Intelligence. Use when extracting text from documents."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# OCR System

## Azure Document Intelligence Setup
```typescript
import { DocumentAnalysisClient, AzureKeyCredential } from '@azure/ai-form-recognizer';

const client = new DocumentAnalysisClient(
  process.env.AZURE_DOCUMENT_ENDPOINT,
  new AzureKeyCredential(process.env.AZURE_DOCUMENT_KEY)
);
```

## Analyze Document
```typescript
async function analyzeDocument(url: string) {
  const poller = await client.beginAnalyzeDocumentFromUrl(
    'prebuilt-document',
    url
  );
  
  const result = await poller.pollUntilDone();
  
  return {
    text: result.content,
    tables: result.tables,
    keyValuePairs: result.keyValuePairs
  };
}
```

## Extract Specific Fields
```typescript
async function extractInsuranceCard(url: string) {
  const poller = await client.beginAnalyzeDocumentFromUrl(
    'prebuilt-idDocument',
    url
  );
  
  const result = await poller.pollUntilDone();
  const doc = result.documents[0];
  
  return {
    memberId: doc.fields.DocumentNumber?.content,
    name: doc.fields.FirstName?.content + ' ' + doc.fields.LastName?.content,
    expirationDate: doc.fields.ExpirationDate?.content
  };
}
```

## Invoice Processing
```typescript
async function extractInvoice(url: string) {
  const poller = await client.beginAnalyzeDocumentFromUrl(
    'prebuilt-invoice',
    url
  );
  
  const result = await poller.pollUntilDone();
  const invoice = result.documents[0];
  
  return {
    vendorName: invoice.fields.VendorName?.content,
    invoiceTotal: invoice.fields.InvoiceTotal?.value,
    items: invoice.fields.Items?.values
  };
}
```
