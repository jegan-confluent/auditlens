# Diary Entry: 2025-12-19

## Session Summary
- Attempted major dashboard UX refactor based on user feedback
- Added pagination component with rows per page (10, 20, 50, 100, 200)
- Changed defaults: hide_internal=True, time_window=1hr, max_events=5000
- Removed version from header/footer
- Refactored all tabs with consistent columns
- **UNRESOLVED**: Dashboard still shows 0/0 events despite data existing in Kafka
- Added debug info to diagnose the issue

## Key Decisions

- **Pagination over infinite scroll**: User explicitly requested rows per page selector with page navigation - enterprise UX pattern
- **hide_internal=True default**: User wants internal proxy operations hidden by default - customers don't care about system ops
- **Remove version from UI**: User explicitly said "why are you giving the version in the dashboard first of all"
- **Cache TTL 15s**: Reduced from 30s for more responsive data updates
- **Consistent columns across tabs**: Core audit info: Who, What, When, Where, Result

## Challenges & Solutions

- **Session state persistence**: Old browser sessions keep old default values
  - Solution: Tell user to use incognito for fresh session
  - Better solution needed: Force refresh on version change

- **0/0 events bug**: Dashboard shows no data despite Kafka having 299 events
  - Verified data exists via direct Python execution
  - Added debug line to show data flow: Raw → After hide_internal → After Quick Filter
  - **UNRESOLVED** - needs user feedback with debug output

- **is_internal UUID regex too broad**: Was matching org IDs in resourceName
  - Previously set to False, user wanted True
  - May still be causing issues - needs review

## User Preferences Learned

- **Direct communication**: User uses strong language when frustrated - don't defend, just fix
- **Expert expectations**: "Don't fucking lose your expert knowledge" - expects production-quality work
- **Customer perspective**: "Think as an expert from a customer point of view" - audit logs are for WHO did WHAT, WHEN
- **No unnecessary UI elements**: Version numbers, internal details - remove them
- **Tables over text**: Prefers structured data presentation
- **Immediate action**: When corrected, fix immediately - no explanations needed

## Code Patterns Used

- **Pagination with session_state**: Use unique keys per tab (`{tab_key}_page`, `{tab_key}_page_size`)
- **Cache auto-clear on filter change**: Hash filter params, clear cache when hash changes
- **Debug info in production**: Show data flow counts to diagnose issues
- **Consistent column definitions**: Define COLUMNS and COLUMN_CONFIG at module level

## Potential CLAUDE.md Rules

- When dashboard shows 0 data, add visible debug info showing data flow (Raw → Filtered → Final)
- Streamlit session_state persists old values - always test in incognito after changing defaults
- For audit dashboards: prioritize WHO, WHAT, WHEN, WHERE, RESULT columns
- Remove version numbers from user-facing UI unless explicitly requested
- Pagination is expected UX for enterprise dashboards - never just truncate with .head()
- When user is frustrated, focus on fixing not explaining
- Cache auto-clear should trigger when any filter parameter changes
- Test data loading via direct Python execution before debugging UI layer

---
Created: 2025-12-19T18:40:00+05:30
Status: Session incomplete - 0/0 bug unresolved
