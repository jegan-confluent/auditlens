---
name: tamil-english
description: "Tamil to English learning patterns for Tamil-speaking children. Use for SpiralSpeak curriculum."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Tamil-English Learning

## Phonetic Bridging
```typescript
// Tamil sounds that map well to English
const PHONETIC_BRIDGES = {
  'க': ['k', 'g'],   // ka/ga
  'ச': ['s', 'ch'],  // sa/cha
  'த': ['th', 'd'],  // tha/da
  'ப': ['p', 'b'],   // pa/ba
  'ம': ['m'],        // ma
  'ந': ['n'],        // na
  'ர': ['r'],        // ra
  'ல': ['l'],        // la
};

// Words that sound similar in both languages
const COGNATES = [
  { tamil: 'அம்மா', english: 'mama', meaning: 'mother' },
  { tamil: 'அப்பா', english: 'papa', meaning: 'father' },
  { tamil: 'பஸ்', english: 'bus', meaning: 'bus' },
];
```

## Age-Appropriate Vocabulary
```typescript
const VOCABULARY_BY_AGE = {
  '5-6': ['cat', 'dog', 'ball', 'book', 'apple', 'sun', 'moon'],
  '6-7': ['house', 'school', 'teacher', 'friend', 'happy', 'run', 'eat'],
  '7-8': ['beautiful', 'important', 'because', 'different', 'together'],
  '8-9': ['adventure', 'discover', 'imagination', 'responsible']
};
```

## CBSE Alignment
```typescript
// Align with CBSE English curriculum
const CBSE_THEMES_CLASS3 = [
  'my_family', 'my_school', 'animals', 'seasons',
  'festivals', 'food', 'transport', 'plants'
];
```

## Tamil Script Support
```typescript
// Check if text contains Tamil
function containsTamil(text: string): boolean {
  return /[\u0B80-\u0BFF]/.test(text);
}

// Transliterate Tamil to English phonetics
function transliterate(tamil: string): string {
  // Basic transliteration map
  const map: Record<string, string> = {
    'அ': 'a', 'ஆ': 'aa', 'இ': 'i', 'ஈ': 'ee',
    'உ': 'u', 'ஊ': 'oo', 'எ': 'e', 'ஏ': 'ae'
  };
  return tamil.split('').map(c => map[c] || c).join('');
}
```
