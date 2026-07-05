// frontend/src/hooks/useDownloadMemoPdf.ts
// AIRP -- useDownloadMemoPdf hook (T-063)
//
// A React Query mutation (not a query -- there is nothing to cache or
// refetch, this is a one-shot user-triggered side effect) wrapping
// GET /api/v1/analysis/{job_id}/memo/pdf. On success it turns the
// returned Blob into a short-lived `blob:` object URL, drives a
// throwaway <a download> click through it, and revokes the URL
// straight after -- the same "create, click, revoke" pattern browsers
// require for a same-tab Blob download, since this endpoint needs an
// Authorization header and therefore cannot be a plain <a href>.
//
// Deliberately does not use useQuery: the PDF is not app state a
// component reads and re-renders against, it is an on-demand download
// triggered by a click. useMutation gives MemoToolbar.tsx exactly the
// three things it needs -- mutate(), isPending, and isError/error --
// without inventing a queryKey for a resource that is never read back.

import { useMutation, type UseMutationResult } from "@tanstack/react-query";

import { fetchAnalysisMemoPdf } from "@/api/analysis";

export interface DownloadMemoPdfParams {
  accessToken: string;
  jobId: string;
}

/** Turns a PDF Blob into a downloaded file named for the given job, then frees the object URL. */
function triggerBlobDownload(blob: Blob, jobId: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = `AIRP-Investment-Memo-${jobId}.pdf`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(objectUrl);
}

export function useDownloadMemoPdf(): UseMutationResult<void, Error, DownloadMemoPdfParams> {
  return useMutation({
    mutationFn: async ({ accessToken, jobId }: DownloadMemoPdfParams) => {
      const blob = await fetchAnalysisMemoPdf({ accessToken, jobId });
      triggerBlobDownload(blob, jobId);
    },
  });
}
