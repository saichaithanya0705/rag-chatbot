import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, createBrowserRouter } from "react-router-dom";

const ChatPage = lazy(() => import("@/pages/chat/ChatPage"));
const PipelinePage = lazy(() => import("@/pages/pipeline/PipelinePage"));

function RouteFallback() {
  return (
    <div className="route-fallback-shell">
      <div className="route-fallback-card">
        <h1>Opening the workspace</h1>
        <p>Loading the next view so your chat, pipeline, and evidence panel stay in sync.</p>
      </div>
    </div>
  );
}

function withSuspense(element: ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>;
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Navigate replace to="/chat" />,
  },
  {
    path: "/chat",
    element: withSuspense(<ChatPage />),
  },
  {
    path: "/pipeline",
    element: withSuspense(<PipelinePage />),
  },
]);
