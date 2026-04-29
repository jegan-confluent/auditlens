# Frontend Migration

The Next.js frontend lives in `frontend/` and is built alongside Streamlit. Streamlit stays available until the product UI has feature parity and production validation.

## Pages

- `/dashboard`: summary cards, recent events, failures, deletions, and system health.
- `/events`: filters, paginated event table, empty/error/loading states, and detail drawer.
- `/system`: API/DB/forwarder status for operations.

## Components

- `FilterBar.tsx`
- `AuditEventTable.tsx`
- `EventDetailDrawer.tsx`
- `SummaryCards.tsx`
- `SystemStatusPanel.tsx`
- `EmptyState.tsx`
- `LoadingState.tsx`
- `ErrorState.tsx`

## API Configuration

Set:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
```

The frontend intentionally keeps charting light at this stage and prioritizes fast table rendering, clear infra issue states, visible active filters, and a reset path.

## Migration Rule

Do not remove or reroute the Streamlit dashboards until the Next.js UI has passed end-to-end validation against the forwarder-backed database path.

