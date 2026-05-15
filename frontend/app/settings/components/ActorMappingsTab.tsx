"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type ActorMapping,
  createActorMapping,
  deleteActorMapping,
  getActorMappings,
  updateActorMapping,
} from "../../../lib/api";

type MappingRow = ActorMapping & { _editing?: boolean; _new?: boolean };
type RowDraft = { raw_id: string; display_name: string; team: string; notes: string };

export function ActorMappingsTab() {
  const [rows, setRows] = useState<MappingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<RowDraft | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await getActorMappings());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function startAdd() {
    setDraft({ raw_id: "", display_name: "", team: "", notes: "" });
    setEditingId(null);
    setSaveError(null);
  }

  function startEdit(m: MappingRow) {
    setEditingId(m.raw_id);
    setDraft({ raw_id: m.raw_id, display_name: m.display_name, team: m.team ?? "", notes: m.notes ?? "" });
    setSaveError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setDraft(null);
    setSaveError(null);
  }

  async function handleSave() {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (editingId) {
        await updateActorMapping(editingId, {
          raw_id: editingId,
          display_name: draft.display_name,
          team: draft.team || null,
          notes: draft.notes || null,
        });
      } else {
        await createActorMapping({
          raw_id: draft.raw_id,
          display_name: draft.display_name,
          team: draft.team || null,
          notes: draft.notes || null,
        });
      }
      setEditingId(null);
      setDraft(null);
      await load();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(rawId: string) {
    setSaving(true);
    setSaveError(null);
    try {
      await deleteActorMapping(rawId);
      setConfirmDeleteId(null);
      await load();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="muted">Loading…</div>;
  if (error) return <div className="settings-access-denied">Error: {error}</div>;

  return (
    <div className="settings-section">
      <div className="actor-map-header">
        <p className="settings-info" style={{ margin: 0 }}>
          Friendly names for service account and user IDs. These override Confluent IAM resolution.
          The YAML file (<code>actor_mappings.yml</code>) is updated directly.
        </p>
        <button className="settings-save-btn" onClick={startAdd} disabled={draft !== null && editingId === null}>
          + Add mapping
        </button>
      </div>

      {saveError && <p className="settings-access-denied" style={{ marginTop: 8 }}>Error: {saveError}</p>}

      {draft !== null && editingId === null && (
        <div className="actor-map-edit-row">
          <input className="settings-text-input actor-map-input" placeholder="Raw ID (e.g. sa-8nwyn7)"
            value={draft.raw_id} onChange={(e) => setDraft({ ...draft, raw_id: e.target.value })} />
          <input className="settings-text-input actor-map-input" placeholder="Display name"
            value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} />
          <input className="settings-text-input actor-map-input" placeholder="Team (optional)"
            value={draft.team} onChange={(e) => setDraft({ ...draft, team: e.target.value })} />
          <input className="settings-text-input actor-map-input" placeholder="Notes (optional)"
            value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
          <div className="actor-map-actions">
            <button className="settings-save-btn actor-map-btn" onClick={handleSave} disabled={saving || !draft.raw_id || !draft.display_name}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button className="settings-test-btn actor-map-btn" onClick={cancelEdit} disabled={saving}>Cancel</button>
          </div>
        </div>
      )}

      {rows.length === 0 && draft === null ? (
        <p className="muted" style={{ marginTop: 16 }}>
          No actor mappings yet. Add one to give friendly names to service account IDs.
        </p>
      ) : (
        <table className="actor-map-table">
          <thead>
            <tr>
              <th>Raw ID</th>
              <th>Display Name</th>
              <th>Team</th>
              <th>Notes</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              editingId === m.raw_id && draft ? (
                <tr key={m.raw_id} className="actor-map-editing">
                  <td><code>{m.raw_id}</code></td>
                  <td><input className="settings-text-input actor-map-input"
                    value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} /></td>
                  <td><input className="settings-text-input actor-map-input" placeholder="—"
                    value={draft.team} onChange={(e) => setDraft({ ...draft, team: e.target.value })} /></td>
                  <td><input className="settings-text-input actor-map-input" placeholder="—"
                    value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></td>
                  <td className="actor-map-actions">
                    <button className="settings-save-btn actor-map-btn" onClick={handleSave} disabled={saving || !draft.display_name}>
                      {saving ? "…" : "Save"}
                    </button>
                    <button className="settings-test-btn actor-map-btn" onClick={cancelEdit} disabled={saving}>Cancel</button>
                  </td>
                </tr>
              ) : confirmDeleteId === m.raw_id ? (
                <tr key={m.raw_id} className="actor-map-confirm-delete">
                  <td colSpan={4} className="actor-map-confirm-msg">
                    Remove mapping for <code>{m.raw_id}</code>?
                  </td>
                  <td className="actor-map-actions">
                    <button className="settings-save-btn actor-map-btn actor-map-danger" onClick={() => handleDelete(m.raw_id)} disabled={saving}>
                      {saving ? "…" : "Confirm"}
                    </button>
                    <button className="settings-test-btn actor-map-btn" onClick={() => setConfirmDeleteId(null)} disabled={saving}>Cancel</button>
                  </td>
                </tr>
              ) : (
                <tr key={m.raw_id}>
                  <td><code>{m.raw_id}</code></td>
                  <td>{m.display_name}</td>
                  <td className="muted">{m.team ?? "—"}</td>
                  <td className="muted">{m.notes ?? "—"}</td>
                  <td className="actor-map-actions">
                    <button className="settings-test-btn actor-map-btn" onClick={() => startEdit(m)}>Edit</button>
                    <button className="settings-test-btn actor-map-btn" onClick={() => setConfirmDeleteId(m.raw_id)}>Delete</button>
                  </td>
                </tr>
              )
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
