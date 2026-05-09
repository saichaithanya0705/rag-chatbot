import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import type { PipelineDocument, PipelineStatus } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { SectionLabel } from "@/shared/ui/section-label/SectionLabel";
import { StatusPill } from "@/shared/ui/status-pill/StatusPill";
import { SurfaceCard } from "@/shared/ui/surface-card/SurfaceCard";
import { KnowledgeGraphView } from "@/widgets/pipeline-shell/KnowledgeGraphView";
import baseStyles from "@/widgets/workbench-frame/workbench-frame.module.css";
import localStyles from "./pipeline-view.module.css";

const styles = { ...baseStyles, ...localStyles };

interface PipelineViewProps {
  active: boolean;
}

type ViewMode = "list" | "card";

function statusLabel(status: PipelineStatus) {
  if (status === "indexed") {
    return "Indexed";
  }

  if (status === "error") {
    return "Error";
  }

  if (status === "parsing") {
    return "Parsing…";
  }

  if (status === "ocr") {
    return "OCR…";
  }

  if (status === "chunking") {
    return "Chunking…";
  }

  if (status === "embedding") {
    return "Embedding…";
  }

  if (status === "clustering") {
    return "Clustering…";
  }

  return "Queued";
}

function statusTone(status: PipelineStatus): "neutral" | "accent" | "warning" | "success" {
  if (status === "indexed") {
    return "success";
  }

  if (status === "error") {
    return "warning";
  }

  if (status === "queued") {
    return "neutral";
  }

  return "accent";
}

function progressClassName(status: PipelineStatus) {
  if (status === "embedding" || status === "clustering") {
    return styles.progBarEmbedding;
  }

  if (status === "indexed") {
    return styles.progBarDone;
  }

  return styles.progBarChunking;
}

function isInFlight(status: PipelineStatus) {
  return status !== "indexed" && status !== "error" && status !== "queued";
}

function FileIcon() {
  return (
    <svg className={styles.fileIconSvg} fill="none" height="16" viewBox="0 0 16 16" width="16">
      <rect height="14" rx="1.5" stroke="currentColor" strokeWidth="1.2" width="10" x="3" y="1" />
      <path d="M5 5h6M5 8h6M5 11h4" stroke="currentColor" strokeLinecap="round" strokeWidth="1" />
    </svg>
  );
}

interface AccordionSectionProps {
  actions?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  title: string;
}

function AccordionSection({ actions, children, defaultOpen = true, title }: AccordionSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <details
      className={styles.accordion}
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
      }}
      open={open}
    >
      <div className={styles.accordionHeader}>
        <summary className={styles.accordionSummary}>
          <div className={styles.accordionSummaryHeading}>
            <svg className={styles.accordionChevron} fill="none" height="14" viewBox="0 0 14 14" width="14">
              <path
                d="M4.5 2.75L8.75 7L4.5 11.25"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.5"
              />
            </svg>
            <SectionLabel as="h2">{title}</SectionLabel>
          </div>
        </summary>
        {actions ? <div className={styles.accordionActions}>{actions}</div> : null}
      </div>
      <div className={styles.accordionContent}>{children}</div>
    </details>
  );
}

export function PipelineView({ active }: PipelineViewProps) {
  const navigate = useNavigate();
  const { state, actions } = useWorkbench();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const confirmDeleteButtonRef = useRef<HTMLButtonElement | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [deletingFileId, setDeletingFileId] = useState<string | null>(null);
  const collectionOptions =
    state.collections.length > 0 ? state.collections : [{ id: "all-pdfs", label: "All PDFs" }];
  const activeCollectionId = state.activeCollectionId || "all-pdfs";
  const activeCollectionLabel =
    collectionOptions.find((collection) => collection.id === activeCollectionId)?.label ?? "All PDFs";
  const canRecluster =
    state.knowledgeBaseSummary.indexedDocuments > 0 && state.knowledgeBaseSummary.indexedChunks > 0;
  const visibleDocuments =
    activeCollectionId === "all-pdfs"
      ? state.pipelineDocuments
      : state.pipelineDocuments.filter((document) =>
          document.topicCollectionIds.includes(activeCollectionId),
        );

  useEffect(() => {
    if (!deletingFileId) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setDeletingFileId((current) => (current === deletingFileId ? null : current));
    }, 3000);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [deletingFileId]);

  useEffect(() => {
    if (deletingFileId && !state.pipelineDocuments.some((document) => document.id === deletingFileId)) {
      setDeletingFileId(null);
    }
  }, [deletingFileId, state.pipelineDocuments]);

  useEffect(() => {
    if (!deletingFileId) {
      return;
    }

    const focusFrame = window.requestAnimationFrame(() => {
      confirmDeleteButtonRef.current?.focus();
    });

    return () => {
      window.cancelAnimationFrame(focusFrame);
    };
  }, [deletingFileId]);

  function handleSelectedFiles(files: FileList | null) {
    if (!files || files.length === 0) {
      return;
    }

    void actions.uploadDocuments(Array.from(files));
  }

  function handleDeleteIntent(documentId: string) {
    setDeletingFileId(documentId);
  }

  function cancelDeleteIntent() {
    setDeletingFileId(null);
  }

  async function confirmDelete(documentId: string) {
    setDeletingFileId(null);
    await actions.removePipelineDocument(documentId);
  }

  function renderDeleteActions(documentId: string, documentName: string, compact = false) {
    if (deletingFileId === documentId) {
      return (
        <div className={cn(styles.fileDeleteConfirm, compact && styles.fileDeleteConfirmCompact)}>
          <button
            aria-label={`Confirm delete ${documentName}`}
            className={styles.confirmDeleteButton}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              void confirmDelete(documentId);
            }}
            ref={(element) => {
              if (deletingFileId === documentId) {
                confirmDeleteButtonRef.current = element;
              }
            }}
            type="button"
          >
            Delete now
          </button>
          <button
            aria-label={`Cancel delete ${documentName}`}
            className={styles.cancelDeleteButton}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              cancelDeleteIntent();
            }}
            type="button"
          >
            Keep
          </button>
        </div>
      );
    }

    return (
      <button
        aria-label={`Delete ${documentName}`}
        className={compact ? styles.fileDeleteCorner : styles.fileDeleteButton}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          handleDeleteIntent(documentId);
        }}
        type="button"
      >
        ×
      </button>
    );
  }

  function renderDocumentListItem(document: PipelineDocument) {
    return (
      <SurfaceCard className={styles.fileRow} key={document.id}>
        <div className={styles.fileRowLead}>
          <FileIcon />
          <div className={styles.fileInfo}>
            <div className={styles.fileTitleRow}>
              <div className={styles.fileName}>{document.name}</div>
              <div className={styles.fileMeta}>
                {document.metaLabel ??
                  `${document.sizeLabel} · ${document.pageCount} pages${
                    document.addedLabel ? ` · ${document.addedLabel}` : ""
                  }`}
              </div>
            </div>
            <div className={styles.fileTopicRow}>
              <span className={styles.fileChunkStat}>{document.chunkCount} chunks</span>
              {document.topics.map((topic) => (
                <span className={styles.fileTopicChip} key={`${document.id}-${topic}`}>
                  {topic}
                </span>
              ))}
            </div>
            {document.sharedTopicSummary ? (
              <div className={styles.fileSharedTopic}>{document.sharedTopicSummary}</div>
            ) : null}
            {isInFlight(document.status) ? (
              <div className={styles.progWrap}>
                <div
                  className={cn(styles.progBar, progressClassName(document.status))}
                  style={{ width: `${document.progress}%` }}
                />
              </div>
            ) : null}
          </div>
        </div>
        <div className={styles.fileRowAside}>
          <StatusPill className={styles.fileStatus} label={statusLabel(document.status)} tone={statusTone(document.status)} />
          {renderDeleteActions(document.id, document.name)}
        </div>
      </SurfaceCard>
    );
  }

  function renderDocumentCard(document: PipelineDocument) {
    return (
      <SurfaceCard className={styles.fileCard} key={document.id}>
        {renderDeleteActions(document.id, document.name, true)}
        <div className={styles.fileCardHeader}>
          <div className={styles.fileCardLead}>
            <FileIcon />
            <div>
              <div className={styles.fileName}>{document.name}</div>
              <div className={styles.fileCardMeta}>
                {document.metaLabel ??
                  `${document.sizeLabel} · ${document.pageCount} pages${
                    document.addedLabel ? ` · ${document.addedLabel}` : ""
                  }`}
              </div>
            </div>
          </div>
          <StatusPill className={styles.fileStatus} label={statusLabel(document.status)} tone={statusTone(document.status)} />
        </div>
        <div className={styles.fileCardFooter}>
          <div className={styles.fileTopicRow}>
            <span className={styles.fileChunkStat}>{document.chunkCount} chunks</span>
            {document.topics.map((topic) => (
              <span className={styles.fileTopicChip} key={`${document.id}-${topic}`}>
                {topic}
              </span>
            ))}
          </div>
          {document.sharedTopicSummary ? (
            <div className={styles.fileSharedTopic}>{document.sharedTopicSummary}</div>
          ) : null}
          {isInFlight(document.status) ? (
            <div className={styles.progWrap}>
              <div
                className={cn(styles.progBar, progressClassName(document.status))}
                style={{ width: `${document.progress}%` }}
              />
            </div>
          ) : null}
        </div>
      </SurfaceCard>
    );
  }

  return (
    <div className={cn(styles.view, active && styles.viewActive)}>
      <div className={styles.pipelineTopbar}>
        <button
          aria-label="Back to chat"
          className={styles.iconBtn}
          onClick={() => void navigate("/chat")}
          type="button"
        >
          <svg fill="none" height="14" viewBox="0 0 16 16" width="14">
            <path
              d="M10 3L5 8L10 13"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="1.5"
            />
          </svg>
        </button>
        <div className={styles.pipelineTitleGroup}>
          <h1 className={styles.pipelineTitle}>PDF pipeline</h1>
          <p className={styles.pipelineSubhead}>
            Upload files, review indexing progress, and keep topic clusters organized.
          </p>
        </div>
        <div className={styles.topbarSpacer} />
        <span className={styles.collectionSummary}>
          Collection: <strong>{activeCollectionLabel}</strong>
        </span>
      </div>

      <div className={styles.pipelineBody}>
        <SurfaceCard className={styles.collectionsSurface}>
          <div className={styles.collectionsHeader}>
            <SectionLabel as="h2">Collections</SectionLabel>
            <div className={styles.collectionInsights}>
              <span className={styles.collectionStat}>{state.knowledgeBaseSummary.indexedDocuments} docs</span>
              <span className={styles.collectionStat}>{state.knowledgeBaseSummary.indexedChunks} chunks</span>
            </div>
          </div>
          <div className={styles.collectionRow}>
            {collectionOptions.map((collection) => (
              <button
                aria-pressed={collection.id === activeCollectionId}
                className={cn(styles.colPill, collection.id === activeCollectionId && styles.colPillActive)}
                key={collection.id}
                onClick={() => actions.selectCollection(collection.id)}
                type="button"
              >
                {collection.label}
              </button>
            ))}
          </div>
          <div className={styles.clusterActionRow}>
            <button
              className={cn(styles.reclusterBtn, state.isReclustering && styles.reclusterBtnBusy)}
              disabled={state.isReclustering || !canRecluster}
              onClick={() => void actions.reclusterTopics()}
              type="button"
            >
              {state.isReclustering ? "Re-clustering..." : "Re-cluster topics"}
            </button>
          </div>
        </SurfaceCard>

        <AccordionSection title="Upload PDFs">
          <SurfaceCard className={styles.uploadSurface}>
            <input
              accept=".pdf,application/pdf"
              hidden
              multiple
              onChange={(event) => {
                handleSelectedFiles(event.target.files);
                event.target.value = "";
              }}
              ref={fileInputRef}
              type="file"
            />
            <div
              className={cn(
                styles.dropZone,
                visibleDocuments.length > 0 && styles.dropZoneCompact,
                dragOver && styles.dropZoneDragOver,
              )}
              onClick={() => fileInputRef.current?.click()}
              onDragLeave={() => setDragOver(false)}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOver(true);
              }}
              onDrop={(event) => {
                event.preventDefault();
                setDragOver(false);
                handleSelectedFiles(event.dataTransfer.files);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              aria-label="Upload PDF files"
              role="button"
              tabIndex={0}
            >
              <svg className={styles.dropIconSvg} fill="none" height="32" viewBox="0 0 32 32" width="32">
                <path
                  d="M16 22V10M16 10L11 15M16 10L21 15"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.5"
                />
                <path d="M6 24h20" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
              </svg>
              <div className={styles.dropTitle}>
                {visibleDocuments.length > 0 ? "Click to upload more PDFs" : "Drop PDFs here or click to browse"}
              </div>
              <div className={styles.dropSub}>Supports text-based PDFs · Max 50 MB each</div>
            </div>
          </SurfaceCard>
        </AccordionSection>

        <AccordionSection
          actions={
            <div className={styles.viewToggle}>
              <button
                aria-pressed={viewMode === "list"}
                className={cn(styles.viewToggleButton, viewMode === "list" && styles.viewToggleButtonActive)}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  setViewMode("list");
                }}
                type="button"
              >
                <svg fill="none" height="14" viewBox="0 0 14 14" width="14">
                  <path d="M3 4h8M3 7h8M3 10h8" stroke="currentColor" strokeLinecap="round" strokeWidth="1.4" />
                </svg>
                <span>List</span>
              </button>
              <button
                aria-pressed={viewMode === "card"}
                className={cn(styles.viewToggleButton, viewMode === "card" && styles.viewToggleButtonActive)}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  setViewMode("card");
                }}
                type="button"
              >
                <svg fill="none" height="14" viewBox="0 0 14 14" width="14">
                  <rect height="4" rx="0.8" stroke="currentColor" strokeWidth="1.1" width="4" x="2" y="2" />
                  <rect height="4" rx="0.8" stroke="currentColor" strokeWidth="1.1" width="4" x="8" y="2" />
                  <rect height="4" rx="0.8" stroke="currentColor" strokeWidth="1.1" width="4" x="2" y="8" />
                  <rect height="4" rx="0.8" stroke="currentColor" strokeWidth="1.1" width="4" x="8" y="8" />
                </svg>
                <span>Cards</span>
              </button>
            </div>
          }
          title="Files in this collection"
        >
          {visibleDocuments.length === 0 ? (
            <SurfaceCard className={styles.emptyState}>
              <div className={styles.emptyStateHeading}>No PDFs in this collection yet</div>
              <div className={styles.emptyStateSub}>
                Upload a document to start building topic clusters, citations, and session-aware answers.
              </div>
            </SurfaceCard>
          ) : viewMode === "list" ? (
            <div className={styles.fileList}>{visibleDocuments.map(renderDocumentListItem)}</div>
          ) : (
            <div className={styles.fileGrid}>{visibleDocuments.map(renderDocumentCard)}</div>
          )}
        </AccordionSection>

        <AccordionSection title="Knowledge Graph">
          <SurfaceCard className={styles.graphSurface}>
            <KnowledgeGraphView
              activeCollectionId={activeCollectionId}
              graph={state.knowledgeGraph}
              onSelectNode={(collectionId) => {
                actions.selectCollection(collectionId);
                void navigate("/chat");
              }}
            />
          </SurfaceCard>
        </AccordionSection>
      </div>
    </div>
  );
}
