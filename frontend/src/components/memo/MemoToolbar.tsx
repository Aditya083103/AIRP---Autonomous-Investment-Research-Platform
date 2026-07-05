// frontend/src/components/memo/MemoToolbar.tsx
// AIRP -- Investment Memo toolbar (T-063)
//
// The two actions the Investment Memo page's acceptance criteria call
// for, side by side above the memo body: "Download PDF" (calls GET
// /api/v1/analysis/{job_id}/memo/pdf via useDownloadMemoPdf) and
// "Share" (copies the current page URL to the clipboard so the reader
// can hand the link to someone else). Both are deliberately
// self-contained here -- the toolbar owns its own copy-feedback state
// rather than pushing it up to MemoPage.tsx, since neither the
// "Copied!" flash nor the PDF-download error message needs to be
// visible to, or affect, anything else on the page.

import { useEffect, useState } from "react";

import { Button } from "@/components/ui";
import { useDownloadMemoPdf } from "@/hooks/useDownloadMemoPdf";

export interface MemoToolbarProps {
  accessToken: string;
  jobId: string;
  /** The URL to copy on Share. Defaults to the current page's URL. */
  shareUrl?: string;
}

type CopyState = "idle" | "copied" | "error";

const COPY_FEEDBACK_DURATION_MS = 2000;

/**
 * Copies text to the clipboard, falling back to a hidden textarea in
 * environments without navigator.clipboard.
 */
async function copyToClipboard(text: string): Promise<void> {
  const clipboard = navigator.clipboard;
  if (clipboard?.writeText) {
    await clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

/** "Download PDF" + "Share" actions for the Investment Memo page. */
export function MemoToolbar({ accessToken, jobId, shareUrl }: MemoToolbarProps): JSX.Element {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const downloadPdf = useDownloadMemoPdf();

  useEffect(() => {
    if (copyState === "idle") {
      return;
    }
    const timer = window.setTimeout(() => setCopyState("idle"), COPY_FEEDBACK_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  async function handleShare(): Promise<void> {
    const urlToCopy = shareUrl ?? window.location.href;
    try {
      await copyToClipboard(urlToCopy);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }

  function handleDownload(): void {
    downloadPdf.mutate({ accessToken, jobId });
  }

  return (
    <div className="flex flex-wrap items-center gap-3" data-testid="memo-toolbar">
      <Button
        type="button"
        variant="primary"
        size="sm"
        isLoading={downloadPdf.isPending}
        onClick={handleDownload}
      >
        Download PDF
      </Button>
      <Button type="button" variant="secondary" size="sm" onClick={() => void handleShare()}>
        {copyState === "copied" ? "Link copied!" : "Share"}
      </Button>

      {downloadPdf.isError ? (
        <p className="text-sm text-verdict-sell" role="alert">
          {downloadPdf.error instanceof Error
            ? downloadPdf.error.message
            : "Could not download the PDF. Please try again."}
        </p>
      ) : null}

      {copyState === "error" ? (
        <p className="text-sm text-verdict-sell" role="alert">
          {"Could not copy the link. Please copy it from your browser's address bar."}
        </p>
      ) : null}
    </div>
  );
}
