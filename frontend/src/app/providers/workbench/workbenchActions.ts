import { useMemo, useRef } from "react";
import type { WorkbenchActions } from "./workbenchTypes";

export const WORKBENCH_ACTION_KEYS = [
  "retryBootstrap",
  "createSession",
  "selectSession",
  "deleteSession",
  "toggleSidebar",
  "setSidebarOpen",
  "selectCollection",
  "setDraftMessage",
  "toggleWebSearch",
  "toggleThinking",
  "sendMessage",
  "openPdfPreview",
  "goToPdfPreviewPage",
  "retryPdfPreview",
  "closePdfPreview",
  "uploadDocuments",
  "reclusterTopics",
  "removePipelineDocument",
  "clearToast",
] satisfies (keyof WorkbenchActions)[];

export function makeWorkbenchActionProxy(actionsRef: { current: WorkbenchActions }): WorkbenchActions {
  return {
    retryBootstrap: (...args) => actionsRef.current.retryBootstrap(...args),
    createSession: (...args) => actionsRef.current.createSession(...args),
    selectSession: (...args) => actionsRef.current.selectSession(...args),
    deleteSession: (...args) => actionsRef.current.deleteSession(...args),
    toggleSidebar: (...args) => actionsRef.current.toggleSidebar(...args),
    setSidebarOpen: (...args) => actionsRef.current.setSidebarOpen(...args),
    selectCollection: (...args) => actionsRef.current.selectCollection(...args),
    setDraftMessage: (...args) => actionsRef.current.setDraftMessage(...args),
    toggleWebSearch: (...args) => actionsRef.current.toggleWebSearch(...args),
    toggleThinking: (...args) => actionsRef.current.toggleThinking(...args),
    sendMessage: (...args) => actionsRef.current.sendMessage(...args),
    openPdfPreview: (...args) => actionsRef.current.openPdfPreview(...args),
    goToPdfPreviewPage: (...args) => actionsRef.current.goToPdfPreviewPage(...args),
    retryPdfPreview: (...args) => actionsRef.current.retryPdfPreview(...args),
    closePdfPreview: (...args) => actionsRef.current.closePdfPreview(...args),
    uploadDocuments: (...args) => actionsRef.current.uploadDocuments(...args),
    reclusterTopics: (...args) => actionsRef.current.reclusterTopics(...args),
    removePipelineDocument: (...args) => actionsRef.current.removePipelineDocument(...args),
    clearToast: (...args) => actionsRef.current.clearToast(...args),
  };
}

export function useStableWorkbenchActions(actions: WorkbenchActions): WorkbenchActions {
  const actionsRef = useRef(actions);
  actionsRef.current = actions;
  return useMemo(() => makeWorkbenchActionProxy(actionsRef), []);
}
