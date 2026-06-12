import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import { cn } from "@/shared/lib/cn";
import { ChatComposer } from "@/widgets/chat-shell/ChatComposer";
import { MessageThread } from "@/widgets/chat-shell/MessageThread";
import baseStyles from "@/widgets/workbench-frame/workbench-frame.module.css";
import localStyles from "./chat-view.module.css";

const styles = { ...baseStyles, ...localStyles };

interface ChatViewProps {
  active: boolean;
}

export function ChatView({ active }: ChatViewProps) {
  const navigate = useNavigate();
  const { state, actions } = useWorkbench();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [focusedOptionIndex, setFocusedOptionIndex] = useState(0);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const collectionOptions =
    state.collections.length > 0 ? state.collections : [{ id: "all-pdfs", label: "All PDFs" }];
  const activeCollectionIndex = Math.max(
    0,
    collectionOptions.findIndex((collection) => collection.id === state.activeCollectionId),
  );
  const activeCollectionLabel = collectionOptions[activeCollectionIndex]?.label ?? "All PDFs";
  const isScopeLocked = state.isSendingMessage;

  function focusOption(index: number) {
    optionRefs.current[index]?.focus();
  }

  function closeDropdown(restoreFocus = true) {
    setDropdownOpen(false);
    setFocusedOptionIndex(activeCollectionIndex);
    if (restoreFocus) {
      window.requestAnimationFrame(() => {
        triggerRef.current?.focus();
      });
    }
  }

  function openDropdown(index = activeCollectionIndex) {
    setFocusedOptionIndex(index);
    setDropdownOpen(true);
  }

  function handleCollectionSelect(collectionId: string) {
    if (isScopeLocked) {
      return;
    }
    actions.selectCollection(collectionId);
    closeDropdown(true);
  }

  useEffect(() => {
    if (!active) {
      return;
    }

    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setDropdownOpen(false);
        setFocusedOptionIndex(activeCollectionIndex);
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }

      if (dropdownOpen) {
        event.preventDefault();
        closeDropdown(true);
        return;
      }

      if (state.pdfPreview) {
        actions.closePdfPreview();
        return;
      }

      if (state.sidebarOpen) {
        actions.toggleSidebar();
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [actions, active, activeCollectionIndex, dropdownOpen, state.pdfPreview, state.sidebarOpen]);

  useEffect(() => {
    if (!active && dropdownOpen) {
      setDropdownOpen(false);
    }
  }, [active, dropdownOpen]);

  useEffect(() => {
    if (isScopeLocked && dropdownOpen) {
      closeDropdown(false);
    }
  }, [dropdownOpen, isScopeLocked]);

  useEffect(() => {
    if (!dropdownOpen) {
      return;
    }

    setFocusedOptionIndex(activeCollectionIndex);
  }, [activeCollectionIndex, dropdownOpen]);

  useEffect(() => {
    if (!dropdownOpen) {
      return;
    }

    const focusFrame = window.requestAnimationFrame(() => {
      focusOption(focusedOptionIndex);
    });

    return () => {
      window.cancelAnimationFrame(focusFrame);
    };
  }, [dropdownOpen, focusedOptionIndex]);

  function handleTriggerKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (isScopeLocked) {
      return;
    }
    const lastIndex = collectionOptions.length - 1;

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        openDropdown((activeCollectionIndex + 1) % collectionOptions.length);
        break;
      case "ArrowUp":
        event.preventDefault();
        openDropdown((activeCollectionIndex - 1 + collectionOptions.length) % collectionOptions.length);
        break;
      case "Home":
        event.preventDefault();
        openDropdown(0);
        break;
      case "End":
        event.preventDefault();
        openDropdown(lastIndex);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        if (dropdownOpen) {
          closeDropdown(true);
        } else {
          openDropdown(activeCollectionIndex);
        }
        break;
      default:
        break;
    }
  }

  function handleOptionKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, optionIndex: number) {
    if (isScopeLocked) {
      return;
    }
    const lastIndex = collectionOptions.length - 1;

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setFocusedOptionIndex((optionIndex + 1) % collectionOptions.length);
        break;
      case "ArrowUp":
        event.preventDefault();
        setFocusedOptionIndex((optionIndex - 1 + collectionOptions.length) % collectionOptions.length);
        break;
      case "Home":
        event.preventDefault();
        setFocusedOptionIndex(0);
        break;
      case "End":
        event.preventDefault();
        setFocusedOptionIndex(lastIndex);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        handleCollectionSelect(collectionOptions[optionIndex].id);
        break;
      case "Escape":
        event.preventDefault();
        closeDropdown(true);
        break;
      default:
        break;
    }
  }

  return (
    <div className={cn(styles.view, active && styles.viewActive)}>
      <div className={styles.chatTopbar}>
        {!state.sidebarOpen && (
          <button
            aria-controls="sidebar"
            aria-expanded={false}
            aria-label="Show history"
            className={cn(styles.iconBtn, styles.hamburgerBtn)}
            onClick={actions.toggleSidebar}
            type="button"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect width="18" height="18" x="3" y="3" rx="2" />
              <path d="M9 3v18" />
              <path d="m14 9 3 3-3 3" />
            </svg>
          </button>
        )}
        <div className={styles.pageTitleGroup}>
          <h1 className={styles.pageTitle}>Research chat</h1>
          <p className={styles.pageSubhead}>Ask across your indexed PDFs and open cited evidence without leaving the thread.</p>
        </div>
        <span className={styles.collectionLabel}>Collection</span>
        <div className={styles.collectionDropdownRef} ref={dropdownRef}>
          <button
            aria-controls="collection-menu"
            aria-expanded={dropdownOpen}
            aria-haspopup="listbox"
            aria-label={`Collection ${activeCollectionLabel}`}
            className={cn(styles.collectionSelect, dropdownOpen && styles.collectionSelectOpen)}
            disabled={isScopeLocked}
            onClick={() => {
              if (isScopeLocked) {
                return;
              }
              if (dropdownOpen) {
                closeDropdown(false);
              } else {
                openDropdown(activeCollectionIndex);
              }
            }}
            onKeyDown={handleTriggerKeyDown}
            ref={triggerRef}
            type="button"
          >
            <span className={styles.collectionSelectLabel}>{activeCollectionLabel}</span>
            <svg fill="none" height="12" viewBox="0 0 12 12" width="12">
              <path
                d="M3 4.5L6 7.5L9 4.5"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.5"
              />
            </svg>
          </button>

          {dropdownOpen ? (
            <div className={styles.collectionMenu} id="collection-menu" role="listbox">
              {collectionOptions.map((collection, optionIndex) => (
                <button
                  aria-selected={state.activeCollectionId === collection.id}
                  className={cn(
                    styles.collectionMenuItem,
                    state.activeCollectionId === collection.id && styles.collectionMenuItemActive,
                  )}
                  disabled={isScopeLocked}
                  key={collection.id}
                  onClick={() => {
                    handleCollectionSelect(collection.id);
                  }}
                  onKeyDown={(event) => {
                    handleOptionKeyDown(event, optionIndex);
                  }}
                  ref={(element) => {
                    optionRefs.current[optionIndex] = element;
                  }}
                  role="option"
                  tabIndex={focusedOptionIndex === optionIndex ? 0 : -1}
                  type="button"
                >
                  {collection.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <div className={styles.topbarSpacer} />
        <div className={styles.toggleCluster}>
          <div className={styles.webToggleWrap}>
            <button
              aria-label={state.webSearchEnabled ? "Turn web search off" : "Turn web search on"}
              aria-pressed={state.webSearchEnabled}
              className={cn(styles.toggleTrack, state.webSearchEnabled && styles.toggleTrackOn)}
              disabled={isScopeLocked}
              onClick={actions.toggleWebSearch}
              type="button"
            >
              <div className={styles.toggleKnob} />
            </button>
            <span className={styles.webToggleLabel}>Web search</span>
            <span
              className={cn(
                styles.offlineBadge,
                state.webSearchEnabled && state.webSearchOffline && styles.offlineBadgeShow,
              )}
            >
              Search offline. PDF answers still work.
            </span>
          </div>
          <div
            className={styles.webToggleWrap}
            style={{ opacity: state.thinkingSupported ? 1 : 0.5 }}
            title={state.thinkingSupported ? undefined : "The currently configured model does not support reasoning"}
          >
            <button
              aria-label={
                state.thinkingEnabled ? "Turn model thinking off" : "Turn model thinking on"
              }
              aria-pressed={state.thinkingEnabled}
              className={cn(styles.toggleTrack, state.thinkingEnabled && styles.toggleTrackOn)}
              disabled={isScopeLocked || !state.thinkingSupported}
              onClick={actions.toggleThinking}
              type="button"
            >
              <div className={styles.toggleKnob} />
            </button>
            <span className={styles.webToggleLabel}>Model thinking</span>
          </div>
          <div className={styles.webToggleWrap}>
            <button
              aria-label={
                state.detailedAnswerEnabled ? "Turn detailed answers off" : "Turn detailed answers on"
              }
              aria-pressed={state.detailedAnswerEnabled}
              className={cn(styles.toggleTrack, state.detailedAnswerEnabled && styles.toggleTrackOn)}
              disabled={isScopeLocked}
              onClick={actions.toggleDetailedAnswer}
              type="button"
            >
              <div className={styles.toggleKnob} />
            </button>
            <span className={styles.webToggleLabel}>Detailed answers</span>
          </div>
        </div>
        <button
          aria-label="Open the PDF pipeline"
          className={cn(styles.iconBtn, styles.pipelineNavBtn)}
          onClick={() => void navigate("/pipeline")}
          type="button"
        >
          <svg fill="none" height="15" viewBox="0 0 16 16" width="15">
            <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.2" width="5" x="2" y="2" />
            <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.2" width="5" x="9" y="2" />
            <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.2" width="5" x="2" y="9" />
            <rect height="5" rx="1" stroke="currentColor" strokeWidth="1.2" width="5" x="9" y="9" />
          </svg>
          <span className={styles.pipelineBtnText}>PDFs</span>
        </button>
      </div>

      <MessageThread />
      <ChatComposer />
    </div>
  );
}
