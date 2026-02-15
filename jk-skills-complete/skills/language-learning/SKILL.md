---
name: language-learning
description: "Language learning curriculum design and spaced repetition. Use for educational apps like SpiralSpeak."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Language Learning

## Spaced Repetition Algorithm (SM-2)
```typescript
interface Card {
  word: string;
  easeFactor: number;  // >= 1.3
  interval: number;    // days
  repetitions: number;
  nextReview: Date;
}

function calculateNextReview(card: Card, quality: number): Card {
  // quality: 0-5 (0=complete blackout, 5=perfect)
  
  if (quality < 3) {
    // Failed - reset
    return { ...card, repetitions: 0, interval: 1 };
  }
  
  let interval: number;
  if (card.repetitions === 0) interval = 1;
  else if (card.repetitions === 1) interval = 6;
  else interval = Math.round(card.interval * card.easeFactor);
  
  const easeFactor = Math.max(1.3, 
    card.easeFactor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
  );
  
  return {
    ...card,
    easeFactor,
    interval,
    repetitions: card.repetitions + 1,
    nextReview: addDays(new Date(), interval)
  };
}
```

## Word Introduction Pattern
```typescript
const DAILY_NEW_WORDS = 5;
const REVIEW_RATIO = 3;  // 3 reviews per 1 new word

async function getDailySession(userId: string) {
  // Get due reviews
  const reviews = await getCardsForReview(userId, DAILY_NEW_WORDS * REVIEW_RATIO);
  
  // Get new words if reviews completed well
  const newWords = await getNewWords(userId, DAILY_NEW_WORDS);
  
  // Interleave for optimal learning
  return shuffle([...reviews, ...newWords]);
}
```

## Progress Tracking
```typescript
interface Progress {
  totalWords: number;
  mastered: number;      // interval > 21 days
  learning: number;      // 1-21 days
  new: number;           // not started
  streak: number;        // consecutive days
}
```
