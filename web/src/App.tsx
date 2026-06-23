import { useState } from "react";
import { DatasetWall } from "./components/DatasetWall";
import { DatasetDetail } from "./components/DatasetDetail";
import { TrajectoryViewer } from "./components/TrajectoryViewer";

type View =
  | { page: "datasets" }
  | { page: "dataset"; id: string; name: string }
  | { page: "trajectory"; hash: string; datasetId?: string; datasetName?: string };

export function App() {
  const [view, setView] = useState<View>({ page: "datasets" });

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
        onOpen={(hash) =>
          setView({ page: "trajectory", hash, datasetId: view.id, datasetName: view.name })
        }
      />
    );
  }
  return (
    <DatasetWall
      onOpen={(id, name) => setView({ page: "dataset", id, name })}
    />
  );
}
