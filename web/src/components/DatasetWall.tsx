import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listDatasets, createDataset, deleteDataset, type Dataset } from "../api";

export function DatasetWall({ onOpen }: { onOpen: (id: string, name: string) => void }) {
  const qc = useQueryClient();
  const { data: datasets = [], isLoading } = useQuery({
    queryKey: ["datasets"],
    queryFn: listDatasets,
  });

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const createMut = useMutation({
    mutationFn: () => createDataset(newName.trim(), newDesc.trim()),
    onSuccess: (ds) => {
      qc.invalidateQueries({ queryKey: ["datasets"] });
      setCreating(false);
      setNewName("");
      setNewDesc("");
      onOpen(ds.id, ds.name);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteDataset(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["datasets"] });
      // ponytail: dataset id is name-derived (_slug), so a recreated same-name
      // dataset reuses this id — drop its cached trajectory pages so they don't
      // bleed into the new dataset. Remove, not invalidate: the id may be gone.
      qc.removeQueries({ queryKey: ["trajectories", id] });
    },
  });

  return (
    <div className="page">
      <div className="page-header">
        <h1>traj-lens</h1>
        <span className="dim">Datasets</span>
        <button className="btn btn-sm" onClick={() => setCreating(true)}>
          + New Dataset
        </button>
      </div>

      {creating && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <div style={{ flex: 1 }}>
              <label className="dim" style={{ fontSize: 12 }}>Name</label>
              <input
                className="input"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g. CodeGen SFT v3"
                autoFocus
                onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && newName.trim() && createMut.mutate()}
              />
            </div>
            <div style={{ flex: 2 }}>
              <label className="dim" style={{ fontSize: 12 }}>Description</label>
              <input
                className="input"
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                placeholder="optional"
              />
            </div>
            <button
              className="btn"
              onClick={() => createMut.mutate()}
              disabled={!newName.trim() || createMut.isPending}
            >
              Create
            </button>
            <button className="btn btn-ghost" onClick={() => setCreating(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="dim">Loading...</div>
      ) : datasets.length === 0 ? (
        <div className="dim">No datasets yet. Create one to get started.</div>
      ) : (
        <div className="ds-grid">
          {datasets.map((ds: Dataset) => (
            <div
              key={ds.id}
              className="ds-card"
              onClick={() => onOpen(ds.id, ds.name)}
            >
              <div className="ds-card-header">
                <span className="ds-card-name">{ds.name}</span>
                {ds.id !== "_default" && (
                  <button
                    className="btn-icon"
                    title="Delete"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`Delete "${ds.name}"?`)) deleteMut.mutate(ds.id);
                    }}
                  >
                    ×
                  </button>
                )}
              </div>
              {ds.description && <div className="dim ds-card-desc">{ds.description}</div>}
              <div className="ds-card-stats">
                <span>{ds.traj_count} trajectories</span>
                <span className="dim">{ds.batch_count} batches</span>
              </div>
              <div className="dim" style={{ fontSize: 11 }}>
                {ds.created_at?.slice(0, 16).replace("T", " ")}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
