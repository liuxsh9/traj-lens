import { DatasetWall } from "./components/DatasetWall";
import { DatasetDetail } from "./components/DatasetDetail";
import { TrajectoryViewer } from "./components/TrajectoryViewer";
import { HelpButton } from "./components/HelpDialog";
import { useSticky } from "./useSticky";

type View =
  | { page: "datasets" }
  | { page: "dataset"; id: string; name: string }
  | { page: "trajectory"; hash: string; datasetId?: string; datasetName?: string };

export function App() {
  const [view, setView] = useSticky<View>("view", { page: "datasets" });

  if (view.page === "trajectory") {
    return (
      <>
        <HelpButton />
        <TrajectoryViewer
          hash={view.hash}
          onBack={() =>
            view.datasetId
              ? setView({ page: "dataset", id: view.datasetId, name: view.datasetName || "" })
              : setView({ page: "datasets" })
          }
        />
      </>
    );
  }
  if (view.page === "dataset") {
    return (
      <>
        <HelpButton />
        <DatasetDetail
          datasetId={view.id}
          datasetName={view.name}
          onBack={() => setView({ page: "datasets" })}
          onDatasetChange={(name) => setView({ page: "dataset", id: view.id, name })}
          onOpen={(hash) =>
            setView({ page: "trajectory", hash, datasetId: view.id, datasetName: view.name })
          }
        />
      </>
    );
  }
  return (
    <>
      <HelpButton />
      <DatasetWall
        onOpen={(id, name) => setView({ page: "dataset", id, name })}
      />
    </>
  );
}
