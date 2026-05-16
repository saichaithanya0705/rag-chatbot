import type { Dispatch, SetStateAction } from "react";
import { httpWorkbenchGateway } from "@/shared/api/httpWorkbench";
import type { Citation, PdfPreviewRequest } from "@/shared/api/types";
import { toPreviewRequest } from "./workbenchStateHelpers";
import type { WorkbenchState } from "./workbenchTypes";

interface PreviewActionDeps {
  state: WorkbenchState;
  setState: Dispatch<SetStateAction<WorkbenchState>>;
  showToast: (message: string) => void;
}

export function createWorkbenchPreviewActions({ state, setState, showToast }: PreviewActionDeps) {
  async function loadPdfPreview(request: PdfPreviewRequest, preserveCurrentPreview = false) {
    setState((previous) => ({
      ...previous,
      isPdfPreviewLoading: true,
      pdfPreviewError: null,
      pdfPreviewRequest: request,
      pdfPreview: preserveCurrentPreview ? previous.pdfPreview : null,
    }));

    try {
      const preview = await httpWorkbenchGateway.getPdfPreview(request);
      setState((previous) => ({
        ...previous,
        isPdfPreviewLoading: false,
        pdfPreview: preview,
        pdfPreviewError: null,
        pdfPreviewRequest: request,
      }));
    } catch (error) {
      setState((previous) => ({
        ...previous,
        isPdfPreviewLoading: false,
        pdfPreviewError: httpWorkbenchGateway.resolveErrorMessage(error),
        pdfPreviewRequest: request,
      }));
    }
  }

  async function openPdfPreview(citation: Citation) {
    try {
      await loadPdfPreview(toPreviewRequest(citation));
    } catch (error) {
      showToast(httpWorkbenchGateway.resolveErrorMessage(error));
    }
  }

  async function goToPdfPreviewPage(page: number) {
    const request = state.pdfPreviewRequest;
    if (!request || page < 1 || page === request.page) {
      return;
    }

    await loadPdfPreview({ ...request, page }, true);
  }

  async function retryPdfPreview() {
    if (!state.pdfPreviewRequest) {
      return;
    }

    await loadPdfPreview(state.pdfPreviewRequest, Boolean(state.pdfPreview));
  }

  function closePdfPreview() {
    setState((previous) => ({
      ...previous,
      pdfPreview: null,
      pdfPreviewError: null,
      pdfPreviewRequest: null,
      isPdfPreviewLoading: false,
    }));
  }

  return {
    openPdfPreview,
    goToPdfPreviewPage,
    retryPdfPreview,
    closePdfPreview,
  };
}
