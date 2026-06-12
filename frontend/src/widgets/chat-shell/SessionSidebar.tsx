import { Fragment, useEffect, useRef, useState } from "react";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import { cn } from "@/shared/lib/cn";
import styles from "./session-sidebar.module.css";

const sessionGroups = ["Today", "Yesterday", "Last 7 days", "Older"] as const;
const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function SessionSidebar() {
  const { state, actions } = useWorkbench();
  const [flashingSessionId, setFlashingSessionId] = useState<string | null>(null);
  const [pendingDeleteSessionId, setPendingDeleteSessionId] = useState<string | null>(null);
  const deleteIntentTimeoutRef = useRef<number | null>(null);
  const sidebarRef = useRef<HTMLDivElement | null>(null);
  const lastFocusedElementRef = useRef<HTMLElement | null>(null);
  const isModal = state.isCompactViewport && state.sidebarOpen;
  const isSessionActionPending = Boolean(state.pendingSessionAction || state.isSendingMessage);

  useEffect(() => {
    return () => {
      if (deleteIntentTimeoutRef.current !== null) {
        window.clearTimeout(deleteIntentTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!isModal) {
      return;
    }

    const dialog = sidebarRef.current;
    if (!dialog) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    lastFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";

    // Focus the first element on open
    const initialFocusable = dialog.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    initialFocusable?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        actions.setSidebarOpen(false);
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      // Re-query every keystroke so the trap stays fresh after session create/delete
      const focusableElements = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
        (element) => !element.hasAttribute("disabled") && element.getAttribute("aria-hidden") !== "true",
      );

      if (focusableElements.length === 0) {
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      lastFocusedElementRef.current?.focus();
    };
  }, [actions, isModal]);

  function triggerDelete(sessionId: string) {
    if (pendingDeleteSessionId === sessionId) {
      setPendingDeleteSessionId(null);
      setFlashingSessionId(null);
      if (deleteIntentTimeoutRef.current !== null) {
        window.clearTimeout(deleteIntentTimeoutRef.current);
        deleteIntentTimeoutRef.current = null;
      }
      void actions.deleteSession(sessionId);
      return;
    }

    if (deleteIntentTimeoutRef.current !== null) {
      window.clearTimeout(deleteIntentTimeoutRef.current);
    }

    setFlashingSessionId(sessionId);
    setPendingDeleteSessionId(sessionId);

    window.setTimeout(() => {
      setFlashingSessionId((current) => (current === sessionId ? null : current));
    }, 180);

    deleteIntentTimeoutRef.current = window.setTimeout(() => {
      setPendingDeleteSessionId((current) => (current === sessionId ? null : current));
      deleteIntentTimeoutRef.current = null;
    }, 3000);
  }

  return (
    <>
      <button
        aria-hidden={!isModal}
        aria-label="Close history"
        className={cn(styles.sidebarBackdrop, state.sidebarOpen && styles.backdropOpen)}
        onPointerDown={(event) => {
          event.preventDefault();
          if (state.sidebarOpen) {
            actions.setSidebarOpen(false);
          }
        }}
        onClick={() => {
          if (state.sidebarOpen) {
            actions.setSidebarOpen(false);
          }
        }}
        tabIndex={isModal ? 0 : -1}
        type="button"
      />
      <div
        aria-hidden={!state.sidebarOpen}
        aria-labelledby="history-panel-title"
        aria-modal={isModal ? "true" : undefined}
        aria-busy={isSessionActionPending}
        className={cn(styles.sidebar, !state.sidebarOpen && styles.sidebarCollapsed)}
        id="sidebar"
        ref={sidebarRef}
        role={isModal ? "dialog" : "complementary"}
      >
        {state.sidebarOpen ? (
          <>
            <div className={styles.sidebarHeader}>
              <div className={styles.sidebarHeaderRow}>
                <div className={styles.sidebarTitleBlock}>
                  <h2 className={styles.sidebarTitle} id="history-panel-title">
                    Recent chats
                  </h2>
                  <p className={styles.sidebarSubhead}>Return to earlier threads or start a fresh one.</p>
                </div>
                <button
                  aria-label="Collapse sidebar"
                  className={styles.collapseSidebarBtn}
                  onClick={() => actions.setSidebarOpen(false)}
                  type="button"
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <rect width="18" height="18" x="3" y="3" rx="2" />
                    <path d="M9 3v18" />
                    <path d="m16 15-3-3 3-3" />
                  </svg>
                </button>
              </div>
              <button
                className={styles.newChatBtn}
                disabled={isSessionActionPending}
                onClick={() => void actions.createSession()}
                type="button"
              >
                <span className={styles.newChatIcon}>+</span>
                <span>{state.pendingSessionAction === "create" ? "Opening..." : "New chat"}</span>
              </button>
            </div>

            <div className={styles.sidebarScroll}>
              {sessionGroups.map((group) => {
                const groupedSessions = state.sessions.filter((session) => session.group === group);
                if (groupedSessions.length === 0) {
                  return null;
                }

                return (
                  <Fragment key={group}>
                    <div className={styles.dateGroup}>{group}</div>
                    {groupedSessions.map((session) => (
                      <div className={styles.sessionRow} key={session.id}>
                        <button
                          className={cn(
                            styles.session,
                            session.id === state.activeSessionId && styles.sessionActive,
                            flashingSessionId === session.id && styles.sessionDeleteFlash,
                            pendingDeleteSessionId === session.id && styles.sessionDeletePending,
                          )}
                          disabled={isSessionActionPending}
                          onClick={() => void actions.selectSession(session.id)}
                          onKeyDown={(event) => {
                            if (event.key === "Delete" || event.key === "Backspace") {
                              event.preventDefault();
                              triggerDelete(session.id);
                            }
                          }}
                          type="button"
                        >
                          <svg className={styles.sessionIcon} fill="none" height="14" viewBox="0 0 16 16" width="14">
                            <path
                              d="M4 5.5H12M4 8.5H9M2 2.5H14C14.5523 2.5 15 2.94772 15 3.5V11.5C15 12.0523 14.5523 12.5 14 12.5H6L2 14.5V2.5Z"
                              stroke="currentColor"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth="1.2"
                            />
                          </svg>
                          <span className={styles.sessionTitle}>
                            {session.title}
                            {state.pendingSessionAction === "select" &&
                            state.pendingSessionTargetId === session.id
                              ? " ..."
                              : ""}
                          </span>
                        </button>
                        <button
                          aria-label={
                            pendingDeleteSessionId === session.id
                              ? `Confirm delete ${session.title}`
                              : `Delete ${session.title}`
                          }
                          className={cn(
                            styles.sessionDelete,
                            pendingDeleteSessionId === session.id && styles.sessionDeletePendingButton,
                          )}
                          disabled={isSessionActionPending}
                          onClick={(event) => {
                            event.stopPropagation();
                            triggerDelete(session.id);
                          }}
                          type="button"
                        >
                          {state.pendingSessionAction === "delete" &&
                          state.pendingSessionTargetId === session.id
                            ? "Deleting..."
                            : pendingDeleteSessionId === session.id
                              ? "Delete now"
                              : "×"}
                        </button>
                      </div>
                    ))}
                  </Fragment>
                );
              })}
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}
