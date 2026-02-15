---
name: supabase-patterns
description: Supabase RLS, RPC, auth
---
# Supabase Patterns

## RLS Policies
```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users view own" ON documents FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own" ON documents FOR INSERT WITH CHECK (auth.uid() = user_id);
```

## RPC Function
```sql
CREATE FUNCTION insert_encrypted(p_data TEXT, p_key TEXT) RETURNS UUID AS $$
  INSERT INTO records (data) VALUES (pgp_sym_encrypt(p_data, p_key)) RETURNING id;
$$ LANGUAGE sql SECURITY DEFINER;
```

## Client
```typescript
const supabase = createBrowserClient(url, anonKey);
const { data } = await supabase.from('users').select('*').eq('id', userId);
```

## Best Practices
- ✅ Always enable RLS
- ✅ Use RPC for sensitive ops
- ❌ Never expose service key
