import { useState } from "react";
import type { Message } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import styles from "./tool-usage-drawer.module.css";

export interface ToolExecutionItem {
  id: string;
  toolName: string;
  displayName: string;
  category: "retrieval" | "web" | "memory" | "scope" | "generic";
  status: "completed" | "running" | "fallback";
  inputSummary?: string;
  inputParameters?: Record<string, string | number | boolean>;
  outputSummary: string;
  itemsFound?: number;
}

export function extractToolExecutionItems(message: Message): ToolExecutionItem[] {
  const items: ToolExecutionItem[] = [];

  // 1. Structured trace steps from backend
  if (message.answerTrace && message.answerTrace.length > 0) {
    message.answerTrace.forEach((step, idx) => {
      let category: ToolExecutionItem["category"] = "generic";
      let toolName = step.kind || "system_action";
      let displayName = step.label || "System Step";
      let inputSummary: string | undefined;
      const inputParameters: Record<string, string | number | boolean> = {};

      if (step.kind === "scope") {
        category = "scope";
        toolName = "scope_filter";
        displayName = "Workspace Scope Filter";
        inputParameters["collection"] = message.collectionLabel || "All PDFs";
        inputParameters["web_search_enabled"] = Boolean(message.webSearchRequested);
        inputSummary = `scope: "${message.collectionLabel || "All PDFs"}"`;
      } else if (step.kind === "memory") {
        category = "memory";
        toolName = "cross_session_memory";
        displayName = "Cross-Session Memory";
        inputParameters["reused_sessions"] = message.crossSessionMemoryUsed || 1;
        inputSummary = `sessions: ${message.crossSessionMemoryUsed || 1}`;
      } else if (step.kind === "retrieval") {
        category = "retrieval";
        toolName = "pdf_vector_search";
        displayName = "PDF Knowledge Retrieval";
        const pdfCitations = message.citations.filter((c) => c.kind === "pdf");
        inputParameters["collection"] = message.collectionLabel || "All PDFs";
        if (pdfCitations.length > 0) {
          inputParameters["retrieved_chunks"] = pdfCitations.length;
          const uniqueDocNames = Array.from(new Set(pdfCitations.map((c) => c.pdfName).filter(Boolean)));
          inputParameters["matched_documents"] = uniqueDocNames.join(", ");
          inputSummary = `${pdfCitations.length} chunks from ${uniqueDocNames[0] || "PDF library"}`;
        }
      } else if (step.kind === "web") {
        category = "web";
        toolName = "live_web_search";
        displayName = "Live Web Search";
        if (message.toolCall?.query) {
          inputParameters["query"] = message.toolCall.query;
          inputSummary = `query: "${message.toolCall.query}"`;
        } else {
          inputSummary = "live web evidence";
        }
      } else if (step.kind === "citations") {
        category = "retrieval";
        toolName = "evidence_grounding";
        displayName = "Evidence Grounding";
        inputParameters["cited_sources"] = message.citations.length;
        inputSummary = `${message.citations.length} cited sources`;
      }

      items.push({
        id: `step-${idx}-${step.kind}`,
        toolName,
        displayName,
        category,
        status: message.status === "thinking" && idx === message.answerTrace!.length - 1 ? "running" : "completed",
        inputSummary,
        inputParameters: Object.keys(inputParameters).length > 0 ? inputParameters : undefined,
        outputSummary: step.detail,
        itemsFound: category === "retrieval" ? message.citations.length : undefined,
      });
    });
    return items;
  }

  // 2. Fallback when answerTrace is not populated
  if (message.toolCall) {
    items.push({
      id: "tool-web-search",
      toolName: "live_web_search",
      displayName: message.toolCall.label || "Live Web Search",
      category: "web",
      status: message.status === "thinking" ? "running" : "completed",
      inputSummary: `query: "${message.toolCall.query}"`,
      inputParameters: { query: message.toolCall.query },
      outputSummary:
        message.status === "thinking"
          ? "Querying live web sources to supplement indexed PDFs."
          : "Supplemented answer with live web evidence.",
    });
  }

  if (message.citations.length > 0) {
    const pdfCount = message.citations.filter((c) => c.kind === "pdf").length;
    if (pdfCount > 0) {
      items.push({
        id: "tool-pdf-retrieval",
        toolName: "pdf_vector_search",
        displayName: "PDF Knowledge Retrieval",
        category: "retrieval",
        status: "completed",
        inputSummary: `scope: "${message.collectionLabel || "All PDFs"}"`,
        inputParameters: {
          collection: message.collectionLabel || "All PDFs",
          retrieved_excerpts: pdfCount,
        },
        outputSummary: `Retrieved and grounded answer in ${pdfCount} cited PDF excerpt(s).`,
        itemsFound: pdfCount,
      });
    }
  }

  if (message.crossSessionMemoryUsed) {
    items.push({
      id: "tool-memory",
      toolName: "cross_session_memory",
      displayName: "Cross-Session Memory",
      category: "memory",
      status: "completed",
      inputSummary: `reused: ${message.crossSessionMemoryUsed} session(s)`,
      inputParameters: { sessions_count: message.crossSessionMemoryUsed },
      outputSummary: `Reused relevant context from ${message.crossSessionMemoryUsed} earlier session(s) in this local workspace.`,
    });
  }

  return items;
}

function renderCategoryIcon(category: ToolExecutionItem["category"]) {
  switch (category) {
    case "retrieval":
      return (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      );
    case "web":
      return (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
      );
    case "memory":
      return (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3Z" />
        </svg>
      );
    case "scope":
      return (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <circle cx="12" cy="12" r="10" />
          <circle cx="12" cy="12" r="6" />
          <circle cx="12" cy="12" r="2" />
        </svg>
      );
    default:
      return (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <polyline points="4 17 10 11 4 5" />
          <line x1="12" y1="19" x2="20" y2="19" />
        </svg>
      );
  }
}

interface ToolUsageDrawerProps {
  message: Message;
}

export function ToolUsageDrawer({ message }: ToolUsageDrawerProps) {
  const [isOpen, setIsOpen] = useState(message.status === "thinking");
  const [expandedStepIds, setExpandedStepIds] = useState<Set<string>>(new Set());

  const toolItems = extractToolExecutionItems(message);

  if (toolItems.length === 0) {
    return null;
  }

  const toggleStep = (id: string) => {
    setExpandedStepIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const isThinking = message.status === "thinking";
  const uniqueCategories = Array.from(new Set(toolItems.map((t) => t.category)));

  return (
    <div className={styles.drawerShell} aria-label="Tool execution activity">
      {/* Top-level collapsible trigger with rotating arrow */}
      <button
        className={cn(styles.triggerBtn, isOpen && styles.triggerBtnOpen)}
        onClick={() => setIsOpen(!isOpen)}
        type="button"
        aria-expanded={isOpen}
      >
        <div className={styles.triggerLeft}>
          <span className={cn(styles.toolIconWrapper, isThinking && styles.toolIconSpinning)}>
            {isThinking ? (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
            ) : (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
              </svg>
            )}
          </span>

          <span className={styles.triggerLabel}>
            {isThinking ? "Executing tools..." : "Tool activity"}
          </span>

          <span className={styles.toolsCountPill}>
            {toolItems.length} {toolItems.length === 1 ? "step" : "steps"}
          </span>

          {/* Quick tool category badges */}
          <div className={styles.categoryPillsGroup}>
            {uniqueCategories.map((cat) => (
              <span key={cat} className={cn(styles.categoryMiniBadge, styles[`badge_${cat}`])}>
                {cat === "retrieval" ? "PDF RAG" : cat === "web" ? "Web Search" : cat === "memory" ? "Memory" : "Scope"}
              </span>
            ))}
          </div>
        </div>

        <div className={styles.triggerRight}>
          <span className={styles.expandHintText}>{isOpen ? "Hide tools" : "View tools"}</span>
          <svg
            className={cn(styles.chevronArrow, isOpen && styles.chevronRotated)}
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </div>
      </button>

      {/* Expanded container with individual collapsible tool dropdowns */}
      {isOpen && (
        <div className={styles.toolsList} role="region" aria-label="Tool execution breakdown">
          {toolItems.map((tool) => {
            const isStepExpanded = expandedStepIds.has(tool.id);

            return (
              <div key={tool.id} className={cn(styles.toolStepCard, isStepExpanded && styles.toolStepCardExpanded)}>
                {/* Collapsible dropdown header for each individual tool */}
                <button
                  className={styles.toolStepHeader}
                  onClick={() => toggleStep(tool.id)}
                  type="button"
                  aria-expanded={isStepExpanded}
                >
                  <div className={styles.toolStepHeaderLeft}>
                    <span className={cn(styles.toolCategoryIcon, styles[`icon_${tool.category}`])}>
                      {renderCategoryIcon(tool.category)}
                    </span>
                    <div className={styles.toolNameBlock}>
                      <span className={styles.toolNameMono}>tool: {tool.toolName}</span>
                      <span className={styles.toolDisplayName}>{tool.displayName}</span>
                    </div>
                  </div>

                  <div className={styles.toolStepHeaderRight}>
                    {tool.inputSummary && (
                      <span className={styles.toolParamSnippet} title={tool.inputSummary}>
                        {tool.inputSummary}
                      </span>
                    )}

                    <span
                      className={cn(
                        styles.toolStatusBadge,
                        tool.status === "running" ? styles.statusRunning : styles.statusSuccess,
                      )}
                    >
                      {tool.status === "running" ? (
                        "Running..."
                      ) : (
                        <>
                          <svg width="8.5" height="8.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                          Success
                        </>
                      )}
                    </span>

                    <svg
                      className={cn(styles.stepChevron, isStepExpanded && styles.stepChevronRotated)}
                      width="11"
                      height="11"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.5"
                    >
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </div>
                </button>

                {/* Collapsible dropdown drawer showing tool usage, parameters & output */}
                {isStepExpanded && (
                  <div className={styles.toolStepDropdown}>
                    {tool.inputParameters && (
                      <div className={styles.toolSubBlock}>
                        <div className={styles.subBlockHeader}>
                          <span className={styles.subBlockTag}>ARGUMENTS</span>
                        </div>
                        <pre className={styles.jsonParamsCode}>
                          {JSON.stringify(tool.inputParameters, null, 2)}
                        </pre>
                      </div>
                    )}

                    <div className={styles.toolSubBlock}>
                      <div className={styles.subBlockHeader}>
                        <span className={styles.subBlockTag}>OUTPUT / EXECUTION RESULT</span>
                      </div>
                      <p className={styles.resultText}>{tool.outputSummary}</p>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
