import { DatasetWall } from "./components/DatasetWall";
import { DatasetDetail } from "./components/DatasetDetail";
import { TrajectoryViewer } from "./components/TrajectoryViewer";
import { getListScrollKey, resetListScrollPosition } from "./components/ListView";
import { useSticky } from "./useSticky";

type View =
  | { page: "datasets" }
  | { page: "dataset"; id: string; name: string }
  | { page: "trajectory"; hash: string; datasetId?: string; datasetName?: string };

type AppScrollStorage = Pick<Storage, "removeItem">;

export function resetDatasetListScrollOnOpen(storage: AppScrollStorage, datasetId: string) {
  resetListScrollPosition(storage, getListScrollKey(datasetId));
}

export function App() {
  const [view, setView] = useSticky<View>("view", { page: "datasets" });

  const openDatasetFromWall = (id: string, name: string) => {
    try { resetDatasetListScrollOnOpen(sessionStorage, id); } catch { /* private mode */ }
    window.scrollTo({ top: 0 });
    setView({ page: "dataset", id, name });
  };

  if (view.page === "trajectory") {
    return (
      <TrajectoryViewer
        hash={view.hash}
        onBack={() =>
          view.datasetId
            ? setView({ page: "dataset", id: view.datasetId, name: view.datasetName || "" })
            : setView({ page: "datasets" })
        }
      />
    );
  }
  if (view.page === "dataset") {
    return (
      <DatasetDetail
        datasetId={view.id}
        datasetName={view.name}
        onBack={() => setView({ page: "datasets" })}
        onDatasetChange={(name) => setView({ page: "dataset", id: view.id, name })}
        onOpen={(hash) =>
          setView({ page: "trajectory", hash, datasetId: view.id, datasetName: view.name })
        }
      />
    );
  }
  return (
    <DatasetWall
      onOpen={openDatasetFromWall}
    />
  );
}
