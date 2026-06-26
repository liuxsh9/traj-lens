import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listDatasets, createDataset, updateDataset, deleteDataset, type Dataset } from "../api";
import { HelpButton } from "./HelpDialog";

export function DatasetWall({ onOpen }: { onOpen: (id: string, name: string) => void }) {
  const qc = useQueryClient();
  const { data: datasets = [], isLoading } = useQuery({
    queryKey: ["datasets"],
    queryFn: listDatasets,
  });

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [editing, setEditing] = useState<{ id: string; name: string; description: string } | null>(null);

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

  const updateMut = useMutation({
    mutationFn: () => {
      if (!editing) throw new Error("no dataset selected");
      return updateDataset(editing.id, {
        name: editing.name.trim(),
        description: editing.description.trim(),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["datasets"] });
      setEditing(null);
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
        <HelpButton />
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
          {datasets.map((ds: Dataset) => {
            const isEditing = editing?.id === ds.id;
            return (
              <div
                key={ds.id}
                className="ds-card"
                onClick={() => !isEditing && onOpen(ds.id, ds.name)}
              >
                {isEditing ? (
                  <div className="ds-edit" onClick={(e) => e.stopPropagation()}>
                    <label className="dim" style={{ fontSize: 12 }}>Name</label>
                    <input
                      className="input"
                      value={editing.name}
                      onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                      autoFocus
                      onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && editing.name.trim() && updateMut.mutate()}
                    />
                    <label className="dim" style={{ fontSize: 12 }}>Description</label>
                    <input
                      className="input"
                      value={editing.description}
                      onChange={(e) => setEditing({ ...editing, description: e.target.value })}
                      placeholder="optional"
                    />
                    <div className="ds-edit-actions">
                      <button
                        className="btn btn-sm"
                        onClick={() => updateMut.mutate()}
                        disabled={!editing.name.trim() || updateMut.isPending}
                      >
                        Save
                      </button>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => setEditing(null)}
                        disabled={updateMut.isPending}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="ds-card-header">
                      <span className="ds-card-name" title={ds.name}>{ds.name}</span>
                      <button
                        className="btn-icon"
                        title="Edit"
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditing({ id: ds.id, name: ds.name, description: ds.description || "" });
                        }}
                      >
                        Edit
                      </button>
                      {ds.id !== "_default" && (
                        <button
                          className="btn-icon btn-icon-danger"
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
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
