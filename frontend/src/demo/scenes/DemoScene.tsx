/** Route element for /demo/:scene: one focused scene at a time. */
import { Navigate, useParams } from "react-router-dom";
import { isScene, scenePath } from "../journey";
import { DetectScene } from "./DetectScene";
import { FlowScene } from "./FlowScene";
import { ReviewScene } from "./ReviewScene";
import { TestScene } from "./TestScene";
import { TrustScene } from "./TrustScene";
import { UnderstandScene } from "./UnderstandScene";

export function DemoScene() {
  const { scene } = useParams();
  if (!isScene(scene)) return <Navigate to={scenePath("flow")} replace />;
  switch (scene) {
    case "flow":
      return <FlowScene />;
    case "detect":
      return <DetectScene />;
    case "understand":
      return <UnderstandScene />;
    case "test":
      return <TestScene />;
    case "review":
      return <ReviewScene />;
    case "trust":
      return <TrustScene />;
  }
}
