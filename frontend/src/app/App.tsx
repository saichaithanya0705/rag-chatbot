import { RouterProvider } from "react-router-dom";
import { router } from "@/app/router";
import { WorkbenchProvider } from "@/app/providers/workbench/WorkbenchProvider";

export function App() {
  return (
    <WorkbenchProvider>
      <a className="skip-nav" href="#main-content">
        Skip to content
      </a>
      <RouterProvider router={router} />
    </WorkbenchProvider>
  );
}
