export default function EmptyState({ diagnostics, activeFilters, onReset, onShowAll }: {
  diagnostics?: string;
  activeFilters?: string[];
  onReset?: () => void;
  onShowAll?: () => void;
}) {
  return (
    <div className="panel empty-state">
      <strong>No events found for current filters</strong>
      <p className="muted">{diagnostics || "Review active filters or system status."}</p>
      {activeFilters?.length ? <p className="filter-chips">{activeFilters.map((filter) => <span key={filter}>{filter}</span>)}</p> : null}
      {onShowAll ? <button onClick={onShowAll}>Show all activity</button> : null}
      {onReset ? <button onClick={onReset}>Reset to decision mode</button> : null}
    </div>
  );
}
