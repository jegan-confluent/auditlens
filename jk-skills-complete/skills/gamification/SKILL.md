---
name: gamification
description: "Gamification patterns including points, streaks, achievements, and leaderboards. Use for engagement features."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Gamification

## Points System
```typescript
const POINT_VALUES = {
  daily_login: 10,
  complete_lesson: 50,
  perfect_score: 100,
  streak_bonus: (days: number) => days * 5,
  first_of_day: 25
};

async function awardPoints(userId: string, action: string, multiplier = 1) {
  const points = POINT_VALUES[action] * multiplier;
  await db.update(users)
    .set({ points: sql`points + ${points}` })
    .where(eq(users.id, userId));
  
  // Check for level up
  await checkLevelUp(userId);
}
```

## Streak System
```typescript
async function updateStreak(userId: string) {
  const user = await getUser(userId);
  const lastActive = new Date(user.lastActiveDate);
  const today = new Date();
  
  const daysSinceActive = differenceInDays(today, lastActive);
  
  if (daysSinceActive === 1) {
    // Continue streak
    await db.update(users)
      .set({ 
        streak: sql`streak + 1`,
        lastActiveDate: today
      })
      .where(eq(users.id, userId));
  } else if (daysSinceActive > 1) {
    // Break streak
    await db.update(users)
      .set({ streak: 1, lastActiveDate: today })
      .where(eq(users.id, userId));
  }
}
```

## Achievements
```typescript
const ACHIEVEMENTS = [
  { id: 'first_lesson', name: 'First Steps', condition: (u) => u.lessonsCompleted >= 1 },
  { id: 'week_streak', name: 'Week Warrior', condition: (u) => u.streak >= 7 },
  { id: 'perfect_10', name: 'Perfect 10', condition: (u) => u.perfectScores >= 10 },
  { id: 'vocabulary_100', name: 'Word Master', condition: (u) => u.wordsLearned >= 100 }
];

async function checkAchievements(userId: string) {
  const user = await getUser(userId);
  const existing = await getUserAchievements(userId);
  
  for (const achievement of ACHIEVEMENTS) {
    if (!existing.includes(achievement.id) && achievement.condition(user)) {
      await awardAchievement(userId, achievement.id);
    }
  }
}
```

## Levels
```typescript
const LEVEL_THRESHOLDS = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500];

function getLevel(points: number): number {
  return LEVEL_THRESHOLDS.findIndex((threshold, i) => 
    points < (LEVEL_THRESHOLDS[i + 1] || Infinity)
  );
}
```
