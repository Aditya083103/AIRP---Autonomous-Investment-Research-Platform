// frontend/src/components/analysis/PdfUploadField.tsx
// AIRP -- Optional PDF upload field (T-058)
//
// Wraps a visually-hidden native <input type="file"> with a styled
// trigger label (clicking any <label htmlFor> opens the native file
// picker -- no JS click-forwarding needed) plus a filename/size preview
// and a Remove action. Validation itself (MIME type, <=10MB size) lives
// in src/lib/validation/analysisSchemas.ts and is called by
// AnalysisPage.tsx on selection -- this component only displays
// whatever error string it's given; it has no validation logic of its
// own.

import { useId, type ChangeEvent } from "react";

import { cn } from "@/lib/cn";

function formatFileSize(bytes: number): string {
  const megabytes = bytes / (1024 * 1024);
  if (megabytes >= 1) {
    return `${megabytes.toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

interface PdfUploadFieldProps {
  file: File | null;
  onChange: (file: File | null) => void;
  error?: string;
}

export function PdfUploadField({ file, onChange, error }: PdfUploadFieldProps): JSX.Element {
  const inputId = useId();
  const errorId = `${inputId}-error`;

  function handleFileChange(event: ChangeEvent<HTMLInputElement>): void {
    const selected = event.target.files?.[0] ?? null;
    onChange(selected);
    // Reset so choosing the same file again still fires onChange (the
    // browser otherwise treats an unchanged <input type="file"> value
    // as a no-op change event).
    event.target.value = "";
  }

  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-sm font-medium text-ink">Annual report (optional)</p>

      <input
        id={inputId}
        type="file"
        accept="application/pdf"
        className="sr-only"
        onChange={handleFileChange}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? errorId : undefined}
      />

      <div className="flex flex-wrap items-center gap-3">
        <label
          htmlFor={inputId}
          className={cn(
            "cursor-pointer rounded-card border border-line bg-surface px-4 py-2 text-sm",
            "font-medium text-ink transition-colors hover:bg-canvas",
          )}
        >
          Choose PDF
        </label>

        {file ? (
          <span className="flex items-center gap-2 text-sm text-muted">
            <span className="max-w-[16rem] truncate" title={file.name}>
              {file.name}
            </span>
            <span className="font-mono text-xs">({formatFileSize(file.size)})</span>
            <button
              type="button"
              onClick={() => onChange(null)}
              className="font-medium text-verdict-sell hover:underline"
            >
              Remove
            </button>
          </span>
        ) : (
          <span className="text-sm text-muted">No file selected</span>
        )}
      </div>

      {error ? (
        <p id={errorId} role="alert" className="text-xs text-verdict-sell">
          {error}
        </p>
      ) : (
        <p className="text-xs text-muted">PDF only, up to 10MB.</p>
      )}
    </div>
  );
}
