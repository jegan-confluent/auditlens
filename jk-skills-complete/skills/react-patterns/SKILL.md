---
name: react-patterns
description: "React 18+ patterns including hooks, performance optimization, and component design. Use when building React components or debugging React apps."
allowed-tools: "Read,Write"
version: 1.0.0
---

# React Patterns

## When to Use
- Building React components
- Using hooks
- Performance optimization
- State management

## Component Structure
```typescript
interface ButtonProps {
  variant: 'primary' | 'secondary';
  onClick: () => void;
  children: React.ReactNode;
  disabled?: boolean;
}

export function Button({ variant, onClick, children, disabled = false }: ButtonProps) {
  return (
    <button className={`btn btn-${variant}`} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}
```

## Custom Hooks
```typescript
function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored) : initialValue;
  });

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value));
  }, [key, value]);

  return [value, setValue] as const;
}
```

## Performance Patterns
```typescript
// Memoize expensive components
const ExpensiveList = React.memo(({ items }) => (
  <ul>{items.map(item => <li key={item.id}>{item.name}</li>)}</ul>
));

// Memoize computed values
const sortedItems = useMemo(() => 
  items.sort((a, b) => a.name.localeCompare(b.name)), 
  [items]
);

// Stable callback references
const handleClick = useCallback(() => {
  doSomething(id);
}, [id]);
```

## Best Practices
- ✅ Use functional components with hooks
- ✅ Keep components small and focused
- ✅ Lift state up when needed
- ✅ Use React.memo sparingly
- ❌ Avoid inline objects in JSX props
