import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { httpWorkbenchGateway, type KnowledgeBaseRecord } from "@/shared/api/httpWorkbench";
import type { PipelineStatus } from "@/shared/api/types";
import { normalizeCollectionId, toStatusMap } from "./workbenchStateHelpers";
import type { WorkbenchState } from "./workbenchTypes";

interface PipelineActionDeps {
  state: WorkbenchState;
  setState: Dispatch<SetStateAction<WorkbenchState>>;
  showToast: (message: string) => void;
  mergeKnowledgeBase: (knowledgeBase: KnowledgeBaseRecord) => void;
  refreshKnowledgeBase: (options?: { announceTransitions?: boolean }) => Promise<KnowledgeBaseRecord>;
  documentStatusRef: MutableRefObject<Record<string, PipelineStatus>>;
}

export function createWorkbenchPipelineActions({
  state,
  setState,
  showToast,
  mergeKnowledgeBase,
  refreshKnowledgeBase,
  documentStatusRef,
}: PipelineActionDeps) {
  async function uploadDocuments(files: File[]) {
    if (files.length === 0) {
      return;
    }

    try {
      const knowledgeBase = await httpWorkbenchGateway.uploadDocuments(files);
      documentStatusRef.current = toStatusMap(knowledgeBase.pipelineDocuments);
      mergeKnowledgeBase(knowledgeBase);
      showToast(`Queued ${files.length} PDF${files.length === 1 ? "" : "s"} for background indexing.`);
    } catch (error) {
      showToast(httpWorkbenchGateway.resolveErrorMessage(error));
    }
  }

  async function reclusterTopics() {
    if (
      state.isReclustering ||
      state.knowledgeBaseSummary.indexedDocuments === 0 ||
      state.knowledgeBaseSummary.indexedChunks === 0
    ) {
      showToast("Upload and index at least one PDF before re-clustering topics.");
      return;
    }

    setState((previous) => ({
      ...previous,
      isReclustering: true,
    }));

    try {
      const result = await httpWorkbenchGateway.reclusterTopics();
      const knowledgeBase = await refreshKnowledgeBase({ announceTransitions: false });

      setState((previous) => ({
        ...previous,
        isReclustering: false,
        collections: knowledgeBase.collections,
        activeCollectionId: normalizeCollectionId(knowledgeBase.collections, previous.activeCollectionId),
        pipelineDocuments: knowledgeBase.pipelineDocuments,
        knowledgeGraph: knowledgeBase.knowledgeGraph,
        knowledgeBaseSummary: knowledgeBase.knowledgeBaseSummary,
      }));

      showToast(
        `Re-clustered ${result.topics.length} topic${result.topics.length === 1 ? "" : "s"} across ${result.documentCount} PDF${result.documentCount === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      setState((previous) => ({
        ...previous,
        isReclustering: false,
      }));
      showToast(httpWorkbenchGateway.resolveErrorMessage(error));
    }
  }

  async function removePipelineDocument(documentId: string) {
    try {
      await httpWorkbenchGateway.deleteDocument(documentId);
      await refreshKnowledgeBase({ announceTransitions: false });
      showToast("Document removed.");
    } catch (error) {
      showToast(httpWorkbenchGateway.resolveErrorMessage(error));
    }
  }

  return {
    uploadDocuments,
    reclusterTopics,
    removePipelineDocument,
  };
}
