---
name: supabase-patterns
description: "Supabase patterns for auth, database, RLS, and realtime. Use when building with Supabase."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# Supabase Patterns

## Client Setup
```typescript
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_ANON_KEY!
);
```

## Row Level Security (RLS)
```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users see own documents" ON documents
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users insert own documents" ON documents
  FOR INSERT WITH CHECK (auth.uid() = user_id);
```

## Queries
```typescript
// Select with filter
const { data, error } = await supabase
  .from('users')
  .select('id, name, profile:profiles(*)')
  .eq('status', 'active')
  .order('created_at', { ascending: false });

// Insert
const { data, error } = await supabase
  .from('users')
  .insert({ name: 'John', email: 'john@example.com' })
  .select()
  .single();
```

## Auth
```typescript
// Sign up
await supabase.auth.signUp({ email, password });

// Sign in
await supabase.auth.signInWithPassword({ email, password });

// Get user
const { data: { user } } = await supabase.auth.getUser();
```

## Realtime
```typescript
supabase.channel('messages')
  .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'messages' }, 
    (payload) => console.log(payload.new))
  .subscribe();
```
