import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { httpWorkbenchGateway } from "@/shared/api/httpWorkbench";
import { normalizeCollectionId, retainKnownSessionMessages } from "./workbenchStateHelpers";
import type { WorkbenchState } from "./workbenchTypes";

interface SessionActionDeps {
  state: WorkbenchState;
  setState: Dispatch<SetStateAction<WorkbenchState>>;
  titleSyncTimeoutRef: MutableRefObject<Map<string, number>>;
  showToast: (message: string) => void;
}

export function createWorkbenchSessionActions({
  state,
  setState,
  titleSyncTimeoutRef,
  showToast,
}: SessionActionDeps) {
  async function refreshSessions(preferredSessionId?: string) {
    const sessions = await httpWorkbenchGateway.listSessions();
    if (sessions.length === 0) {
      return;
    }

    setState((previous) => ({
      ...previous,
      sessions,
      messagesBySession: retainKnownSessionMessages(
        previous.messagesBySession,
        sessions.map((session) => session.id),
      ),
      activeSessionId:
        preferredSessionId && sessions.some((session) => session.id === preferredSessionId)
          ? preferredSessionId
          : previous.activeSessionId && sessions.some((session) => session.id === previous.activeSessionId)
            ? previous.activeSessionId
            : sessions[0].id,
    }));
  }

  function scheduleSessionTitleRefresh(sessionId: string, attempt = 0) {
    const maxAttempts = 12;
    if (attempt >= maxAttempts) {
      titleSyncTimeoutRef.current.delete(sessionId);
      return;
    }

    const existingTimeout = titleSyncTimeoutRef.current.get(sessionId);
    if (existingTimeout !== undefined) {
      window.clearTimeout(existingTimeout);
    }

    const delayMs = attempt === 0 ? 1500 : 3000;
    const timeoutId = window.setTimeout(() => {
      void (async () => {
        try {
          const sessions = await httpWorkbenchGateway.listSessions();
          const matchingSession = sessions.find((session) => session.id === sessionId);
          if (!matchingSession) {
            titleSyncTimeoutRef.current.delete(sessionId);
            return;
          }

          setState((previous) => ({
            ...previous,
            sessions,
            activeSessionId:
              previous.activeSessionId && sessions.some((session) => session.id === previous.activeSessionId)
                ? previous.activeSessionId
                : sessions[0].id,
          }));

          if (matchingSession.title !== "New chat") {
            titleSyncTimeoutRef.current.delete(sessionId);
            return;
          }
        } catch {
          // Keep polling briefly because title generation is asynchronous on the backend.
        }

        scheduleSessionTitleRefresh(sessionId, attempt + 1);
      })();
    }, delayMs);

    titleSyncTimeoutRef.current.set(sessionId, timeoutId);
  }

  async function createSession() {
    if (state.pendingSessionAction) {
      return;
    }

    setState((previous) => ({
      ...previous,
      pendingSessionAction: "create",
      pendingSessionTargetId: null,
    }));

    try {
      const requestedCollectionId = normalizeCollectionId(state.collections, state.activeCollectionId);
      const detail = await httpWorkbenchGateway.createSession(requestedCollectionId);
      const sessions = await httpWorkbenchGateway.listSessions();
      const nextCollectionId = normalizeCollectionId(state.collections, detail.collectionId);

      setState((previous) => ({
        ...previous,
        sessions,
        activeSessionId: detail.session.id,
        activeCollectionId: nextCollectionId,
        messagesBySession: {
          ...retainKnownSessionMessages(
            previous.messagesBySession,
            sessions.map((session) => session.id),
          ),
          [detail.session.id]: detail.messages,
        },
        draftMessage: "",
        pdfPreview: null,
        pdfPreviewError: null,
        pdfPreviewRequest: null,
        isPdfPreviewLoading: false,
        pendingSessionAction: null,
        pendingSessionTargetId: null,
        sidebarOpen: previous.isCompactViewport ? false : previous.sidebarOpen,
      }));
    } catch (error) {
      showToast(httpWorkbenchGateway.resolveErrorMessage(error));
      setState((previous) => ({
        ...previous,
        pendingSessionAction: null,
        pendingSessionTargetId: null,
      }));
    }
  }

  async function selectSession(sessionId: string) {
    if (state.pendingSessionAction || sessionId === state.activeSessionId) {
      return;
    }

    setState((previous) => ({
      ...previous,
      pendingSessionAction: "select",
      pendingSessionTargetId: sessionId,
    }));

    try {
      const detail = await httpWorkbenchGateway.getSession(sessionId);
      const nextCollectionId = normalizeCollectionId(state.collections, detail.collectionId);

      setState((previous) => ({
        ...previous,
        activeSessionId: sessionId,
        activeCollectionId: nextCollectionId,
        messagesBySession: {
          ...previous.messagesBySession,
          [sessionId]: detail.messages,
        },
        draftMessage: "",
        pdfPreview: null,
        pdfPreviewError: null,
        pdfPreviewRequest: null,
        isPdfPreviewLoading: false,
        pendingSessionAction: null,
        pendingSessionTargetId: null,
        sidebarOpen: previous.isCompactViewport ? false : previous.sidebarOpen,
      }));
    } catch (error) {
      showToast(httpWorkbenchGateway.resolveErrorMessage(error));
      setState((previous) => ({
        ...previous,
        pendingSessionAction: null,
        pendingSessionTargetId: null,
      }));
    }
  }

  async function deleteSession(sessionId: string) {
    if (state.pendingSessionAction) {
      return;
    }

    setState((previous) => ({
      ...previous,
      pendingSessionAction: "delete",
      pendingSessionTargetId: sessionId,
    }));

    try {
      await httpWorkbenchGateway.deleteSession(sessionId);
      let sessions = await httpWorkbenchGateway.listSessions();

      if (sessions.length === 0) {
        const detail = await httpWorkbenchGateway.createSession(
          normalizeCollectionId(state.collections, state.activeCollectionId),
        );
        sessions = [detail.session];

        setState((previous) => ({
          ...previous,
          sessions,
          activeSessionId: detail.session.id,
          activeCollectionId: normalizeCollectionId(previous.collections, detail.collectionId),
          messagesBySession: {
            [detail.session.id]: detail.messages,
          },
          draftMessage: "",
          pdfPreview: null,
          pdfPreviewError: null,
          pdfPreviewRequest: null,
          isPdfPreviewLoading: false,
          pendingSessionAction: null,
          pendingSessionTargetId: null,
          sidebarOpen: previous.isCompactViewport ? false : previous.sidebarOpen,
        }));
        showToast("Session deleted.");
        return;
      }

      const nextSessionId =
        state.activeSessionId !== sessionId &&
        sessions.some((session) => session.id === state.activeSessionId)
          ? state.activeSessionId
          : sessions[0].id;
      const shouldLoadNextSession = state.activeSessionId === sessionId || !(nextSessionId in state.messagesBySession);
      const detail = shouldLoadNextSession
        ? await httpWorkbenchGateway.getSession(nextSessionId)
        : null;

      setState((previous) => ({
        ...previous,
        sessions,
        activeSessionId: nextSessionId,
        activeCollectionId: normalizeCollectionId(
          previous.collections,
          detail?.collectionId ?? previous.activeCollectionId,
        ),
        messagesBySession: {
          ...retainKnownSessionMessages(
            previous.messagesBySession,
            sessions.map((session) => session.id),
          ),
          ...(detail
            ? {
                [nextSessionId]: detail.messages,
              }
            : {}),
        },
        draftMessage: "",
        pdfPreview: null,
        pdfPreviewError: null,
        pdfPreviewRequest: null,
        isPdfPreviewLoading: false,
        pendingSessionAction: null,
        pendingSessionTargetId: null,
        sidebarOpen: previous.isCompactViewport ? false : previous.sidebarOpen,
      }));
      showToast("Session deleted.");
    } catch (error) {
      showToast(httpWorkbenchGateway.resolveErrorMessage(error));
      setState((previous) => ({
        ...previous,
        pendingSessionAction: null,
        pendingSessionTargetId: null,
      }));
    }
  }

  return {
    refreshSessions,
    scheduleSessionTitleRefresh,
    createSession,
    selectSession,
    deleteSession,
  };
}
