---
name: diary-system
description: "Personal diary and journal system with mood tracking. Use when building journaling features."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Diary System

## Entry Structure
```typescript
interface DiaryEntry {
  id: string;
  date: Date;
  title?: string;
  content: string;
  mood: 'great' | 'good' | 'okay' | 'bad' | 'terrible';
  tags: string[];
  isPrivate: boolean;
  weather?: string;
  location?: string;
}
```

## Mood Tracking
```typescript
const MOOD_EMOJI = {
  great: '😊',
  good: '🙂',
  okay: '😐',
  bad: '😔',
  terrible: '😢'
};

async function getMoodTrend(userId: string, days: number) {
  const entries = await getEntries(userId, days);
  const moodValues = { great: 5, good: 4, okay: 3, bad: 2, terrible: 1 };
  
  return entries.map(e => ({
    date: e.date,
    value: moodValues[e.mood]
  }));
}
```

## Prompts for Reflection
```typescript
const JOURNAL_PROMPTS = [
  "What made you smile today?",
  "What's one thing you're grateful for?",
  "What challenged you today and how did you handle it?",
  "What would you do differently if you could redo today?",
  "What's one thing you learned today?"
];

function getDailyPrompt(): string {
  const dayOfYear = getDayOfYear(new Date());
  return JOURNAL_PROMPTS[dayOfYear % JOURNAL_PROMPTS.length];
}
```

## Search and Analysis
```typescript
async function searchEntries(userId: string, query: string) {
  return db.query(`
    SELECT * FROM diary_entries 
    WHERE user_id = $1 
    AND content ILIKE $2
    ORDER BY date DESC
  `, [userId, `%${query}%`]);
}
```
