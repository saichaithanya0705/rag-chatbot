import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useWorkbench } from "@/app/providers/workbench/WorkbenchProvider";
import type { PipelineDocument, PipelineStatus } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { AppNavTabs } from "@/shared/ui/app-nav/AppNavTabs";
import { SectionLabel } from "@/shared/ui/section-label/SectionLabel";
import { StatusPill } from "@/shared/ui/status-pill/StatusPill";
import { SurfaceCard } from "@/shared/ui/surface-card/SurfaceCard";
import { buildKnowledgeGraphSummary } from "@/widgets/knowledge-graph-explorer/knowledgeGraphModel";
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
    return "Parsing document…";
  }

  if (status === "ocr") {
    return "Analyzing layout…";
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
        {actions ? <div className={styles.accordionActions}>{actions}</div> : null}
      </summary>
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
  const [expandedErrorDocId, setExpandedErrorDocId] = useState<string | null>(null);
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
  const graphSummary = buildKnowledgeGraphSummary(state.knowledgeGraph);
  const strongestGraphEdges = [...state.knowledgeGraph.edges]
    .sort((left, right) => right.weight - left.weight)
    .slice(0, 3);
  const graphNodeById = new Map(state.knowledgeGraph.nodes.map((node) => [node.id, node]));

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
            Delete
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
        title="Delete document"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 6h18m-2 0v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6m3 0V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
        </svg>
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
              {document.status === "error" ? (
                <div className={styles.fileErrorBlock}>
                  <div className={styles.fileErrorHeader}>
                    <span className={styles.fileErrorBadge}>Ingestion failed</span>
                    {document.metaLabel ? (
                      <button
                        className={styles.errorDetailsBtn}
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setExpandedErrorDocId(
                            expandedErrorDocId === document.id ? null : document.id,
                          );
                        }}
                        type="button"
                      >
                        {expandedErrorDocId === document.id ? "Hide error details" : "View error details"}
                      </button>
                    ) : null}
                  </div>
                  {expandedErrorDocId === document.id ? (
                    <div className={styles.errorPopover}>{document.metaLabel}</div>
                  ) : null}
                </div>
              ) : (
                <div className={styles.fileMeta}>
                  {document.metaLabel ??
                    `${document.sizeLabel} · ${document.pageCount} pages${
                      document.addedLabel ? ` · ${document.addedLabel}` : ""
                    }`}
                </div>
              )}
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
              {document.status === "error" ? (
                <div className={styles.fileErrorBlock}>
                  <div className={styles.fileErrorHeader}>
                    <span className={styles.fileErrorBadge}>Ingestion failed</span>
                    {document.metaLabel ? (
                      <button
                        className={styles.errorDetailsBtn}
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setExpandedErrorDocId(
                            expandedErrorDocId === document.id ? null : document.id,
                          );
                        }}
                        type="button"
                      >
                        {expandedErrorDocId === document.id ? "Hide error details" : "View error details"}
                      </button>
                    ) : null}
                  </div>
                  {expandedErrorDocId === document.id ? (
                    <div className={styles.errorPopover}>{document.metaLabel}</div>
                  ) : null}
                </div>
              ) : (
                <div className={styles.fileCardMeta}>
                  {document.metaLabel ??
                    `${document.sizeLabel} · ${document.pageCount} pages${
                      document.addedLabel ? ` · ${document.addedLabel}` : ""
                    }`}
                </div>
              )}
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
        <div className={styles.pipelineTitleGroup}>
          <h1 className={styles.pipelineTitle}>PDF pipeline</h1>
          <p className={styles.pipelineSubhead}>
            Upload files, review indexing progress, and keep topic clusters organized.
          </p>
        </div>
        <div className={styles.topbarSpacer} />
        <AppNavTabs />
      </div>

      <div className={styles.pipelineBody}>
        {/* Knowledge Base KPI Metrics Card */}
        <SurfaceCard className={styles.metricsDashboardSurface}>
          <div className={styles.metricsRow}>
            <div className={styles.kpiCard}>
              <span className={styles.kpiValue}>{state.knowledgeBaseSummary.indexedDocuments}</span>
              <span className={styles.kpiLabel}>Indexed PDFs</span>
            </div>
            <div className={styles.kpiDivider} />
            <div className={styles.kpiCard}>
              <span className={styles.kpiValue}>{state.knowledgeBaseSummary.indexedChunks}</span>
              <span className={styles.kpiLabel}>Vector Chunks</span>
            </div>
            <div className={styles.kpiDivider} />
            <div className={styles.kpiCard}>
              <span className={styles.kpiValue}>{graphSummary.topicCount}</span>
              <span className={styles.kpiLabel}>Topic Clusters</span>
            </div>
            <div className={styles.kpiActionWrapper}>
              <button
                className={cn(styles.reclusterBtn, state.isReclustering && styles.reclusterBtnBusy)}
                disabled={state.isReclustering || !canRecluster}
                onClick={() => void actions.reclusterTopics()}
                type="button"
                title="Re-run semantic topic clustering algorithm across indexed PDFs"
              >
                {state.isReclustering ? (
                  <>
                    <span className={styles.spinnerIcon} />
                    Re-clustering...
                  </>
                ) : (
                  <>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                    </svg>
                    Re-cluster topics
                  </>
                )}
              </button>
            </div>
          </div>

          <div className={styles.collectionSelectorStrip}>
            <span className={styles.collectionSelectorLabel}>Active Scope:</span>
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
              <div className={styles.dropIconContainer}>
                <svg className={styles.dropIconSvg} fill="none" height="30" viewBox="0 0 24 24" width="30" stroke="currentColor" strokeWidth="1.8">
                  <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242M12 12v9m-4-4 4-4 4 4" />
                </svg>
              </div>
              <div className={styles.dropTitle}>
                Drag &amp; drop PDF files here, or <span className={styles.browseLink}>Browse</span>
              </div>
              <p className={styles.dropSub}>
                Digital text, tables, and layout supported · Max 50 MB per file
              </p>
              <div className={styles.formatBadgesRow}>
                <span className={styles.formatBadge}>.PDF</span>
                <span className={styles.formatBadge}>Tables Preserved</span>
                <span className={styles.formatBadge}>Layout Aware</span>
                <span className={styles.formatBadge}>Auto Chunking</span>
              </div>
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
          <SurfaceCard className={styles.graphPreviewSurface}>
            <div className={styles.graphPreviewHeader}>
              <div>
                <div className={styles.graphPreviewTitle}>Topic relationship map</div>
                <div className={styles.graphPreviewText}>
                  {graphSummary.topicCount === 0
                    ? "Re-cluster indexed PDFs to build a topic map."
                    : `${graphSummary.topicCount} topics · ${graphSummary.relationshipCount} relationships · ${graphSummary.chunkCount} chunks`}
                </div>
              </div>
              <button
                className={styles.graphPreviewAction}
                onClick={() => void navigate("/knowledge-graph")}
                type="button"
              >
                Open graph ➔
              </button>
            </div>
            {strongestGraphEdges.length > 0 ? (
              <div className={styles.graphPreviewLinks}>
                {strongestGraphEdges.map((edge) => {
                  const source = graphNodeById.get(edge.source);
                  const target = graphNodeById.get(edge.target);
                  return (
                    <button
                      className={styles.graphPreviewLink}
                      key={`${edge.source}-${edge.target}`}
                      onClick={() => void navigate(`/knowledge-graph?edge=${[edge.source, edge.target].sort().join("::")}`)}
                      type="button"
                    >
                      <span>{source?.label ?? edge.source}</span>
                      <svg aria-hidden="true" fill="none" height="12" viewBox="0 0 16 12" width="16">
                        <path d="M2 6H14M10 2L14 6L10 10" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.4" />
                      </svg>
                      <span>{target?.label ?? edge.target}</span>
                      <strong>{Math.round(edge.weight * 100)}%</strong>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </SurfaceCard>
        </AccordionSection>
      </div>
    </div>
  );
}
