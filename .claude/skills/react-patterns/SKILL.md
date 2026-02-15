---
name: react-patterns
description: React 18+ patterns and hooks
---
# React Patterns

## Component Structure
```typescript
interface Props { label: string; onClick: () => void; disabled?: boolean; }
export function Button({ label, onClick, disabled = false }: Props) {
  return <button onClick={onClick} disabled={disabled}>{label}</button>;
}
```

## Custom Hook
```typescript
function useData<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(url).then(r => r.json()).then(setData).finally(() => setLoading(false));
  }, [url]);
  return { data, loading };
}
```

## Performance
```typescript
const MemoComponent = memo(ExpensiveComponent);
const handleClick = useCallback(() => doSomething(id), [id]);
const sorted = useMemo(() => items.sort(), [items]);
```

## Best Practices
- ✅ Use functional components
- ✅ Clean up effects
- ❌ Don't mutate state directly
