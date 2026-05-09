import { useEffect, useRef } from "react";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import { Toast } from "@/shared/ui/toast/Toast";
import { ChatView } from "@/widgets/chat-shell/ChatView";
import { SessionSidebar } from "@/widgets/chat-shell/SessionSidebar";
import { PdfViewerPanel } from "@/widgets/pdf-viewer/PdfViewerPanel";
import { PipelineView } from "@/widgets/pipeline-shell/PipelineView";
import styles from "@/widgets/workbench-frame/workbench-frame.module.css";

interface WorkbenchFrameProps {
  activeView: "chat" | "pipeline";
}

function WorkbenchStatePanel({
  actionLabel,
  body,
  onAction,
  title,
}: {
  actionLabel?: string;
  body: string;
  onAction?: () => void;
  title: string;
}) {
  return (
    <section className={styles.stateShell}>
      <div className={styles.stateCard}>
        <h1 className={styles.stateTitle}>{title}</h1>
        <p className={styles.stateBody}>{body}</p>
        {onAction && actionLabel ? (
          <button className={styles.stateAction} onClick={onAction} type="button">
            {actionLabel}
          </button>
        ) : null}
      </div>
    </section>
  );
}

export function WorkbenchFrame({ activeView }: WorkbenchFrameProps) {
  const { state, actions } = useWorkbench();
  const mainRef = useRef<HTMLElement | null>(null);
  const isCompactPdfDialog =
    activeView === "chat" &&
    state.isCompactViewport &&
    Boolean(state.pdfPreview || state.pdfPreviewRequest || state.isPdfPreviewLoading || state.pdfPreviewError);

  useEffect(() => {
    if (activeView === "pipeline" && state.pdfPreviewRequest) {
      actions.closePdfPreview();
    }
  }, [activeView, state.pdfPreviewRequest, actions]);

  useEffect(() => {
    if (activeView === "pipeline" && state.sidebarOpen) {
      actions.setSidebarOpen(false);
    }
  }, [activeView, state.sidebarOpen, actions]);

  useEffect(() => {
    const mainElement = mainRef.current;
    if (!mainElement) {
      return;
    }

    const shouldInert = (state.isCompactViewport && state.sidebarOpen) || isCompactPdfDialog;
    mainElement.toggleAttribute("inert", shouldInert);
    mainElement.setAttribute("aria-hidden", shouldInert ? "true" : "false");

    return () => {
      mainElement.removeAttribute("inert");
      mainElement.removeAttribute("aria-hidden");
    };
  }, [isCompactPdfDialog, state.isCompactViewport, state.sidebarOpen]);

  if (state.isBootstrapping) {
    return (
      <div className={styles.app}>
        <WorkbenchStatePanel
          body="Loading sessions, documents, and topic clusters so the chat and pipeline stay in sync."
          title={activeView === "chat" ? "Opening your research workspace" : "Preparing your PDF pipeline"}
        />
      </div>
    );
  }

  if (state.bootstrapError) {
    return (
      <div className={styles.app}>
        <WorkbenchStatePanel
          actionLabel="Retry loading"
          body={state.bootstrapError}
          onAction={() => void actions.retryBootstrap()}
          title="We couldn't load the workspace"
        />
        <Toast message={state.toastMessage} />
      </div>
    );
  }

  return (
    <div className={styles.app}>
      <SessionSidebar />
      <main className={styles.main} id="main-content" ref={mainRef} tabIndex={-1}>
        {activeView === "chat" ? <ChatView active /> : <PipelineView active />}
      </main>
      <PdfViewerPanel
        open={
          activeView === "chat" &&
          Boolean(state.pdfPreview || state.pdfPreviewRequest || state.isPdfPreviewLoading || state.pdfPreviewError)
        }
      />
      <Toast message={state.toastMessage} />
    </div>
  );
}
