// frontend/src/components/analysis/CompanyAutocomplete.tsx
// AIRP -- Company autocomplete combobox (T-058, rewired B5)
//
// A hand-rolled ARIA combobox (role="combobox" + a role="listbox"
// popup) rather than a native <select> or a headless-UI library --
// no combobox/autocomplete package is already a dependency
// (package.json has none), and pulling one in would need `npm install`
// against a registry this sandbox cannot reach to verify, the same
// constraint every other AIRP frontend task has worked within. The
// interaction pattern follows the W3C ARIA APG combobox-with-listbox
// pattern: arrow keys move a highlighted option, Enter selects it,
// Escape closes the popup, and clicking an option uses onMouseDown
// with preventDefault (not onClick alone) so the input never loses
// focus/fires blur before the click is registered.
//
// Deliberately visually styled to match src/components/ui/Input.tsx
// (T-054) -- same label/box/error layout -- without extending Input
// itself, since Input has no concept of a popup listbox overlay.
//
// B5 rewrite -- what changed and why
// ------------------------------------------------------------------------
// This component used to filter a fixed `options` prop (always
// NSE_TOP_50, 51 entries) entirely client-side and hard-slice to 8
// visible rows -- bug #5's root cause (the dropdown was hard-capped at
// ~50 companies no matter what the person typed). It now debounces the
// person's input and queries GET /api/v1/companies/search
// (backend.services.company_search's ~270-company curated universe),
// paginating further pages in as the listbox is scrolled near its
// bottom (see handleListboxScroll/loadMore below) rather than
// windowing/virtualizing the DOM -- the search endpoint already never
// hands back more than one page's worth of rows at a time, so the
// rendered list only ever grows as far as the person has actually
// scrolled, achieving the same "the whole universe is browsable
// without an unbounded DOM" goal a virtualization library would, with
// no new dependency (this codebase's "no npm install against an
// unreachable registry" constraint, restated above, applies here too).
//
// `fallbackOptions` (defaults to NSE_TOP_50) is used in two cases,
// exactly matching the work order's "keep the Top-50 static list only
// as an offline/first-paint fallback": before `accessToken` is
// available yet (auth still loading), and whenever the search request
// itself fails (network error, backend down) -- a transient failure
// degrades to the old, always-available local list rather than
// leaving the person with an empty, broken-looking dropdown.

import { useEffect, useId, useMemo, useState, type KeyboardEvent, type UIEvent } from "react";

import { CompanyApiError, searchCompanies } from "@/api/companies";
import { Spinner } from "@/components/ui";
import { NSE_TOP_50, type NseCompany } from "@/data/nseTop50";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { cn } from "@/lib/cn";

// Page size for one GET /api/v1/companies/search request -- both the
// initial page (on open / query change) and each subsequent
// infinite-scroll page use this same size.
const SEARCH_PAGE_SIZE = 30;

// How long to wait, after the person stops typing, before firing a
// search request -- long enough to collapse a fast burst of
// keystrokes into one request, short enough that the dropdown still
// feels responsive.
const SEARCH_DEBOUNCE_MS = 250;

// How close (in pixels) to the listbox's bottom edge triggers loading
// the next page.
const LOAD_MORE_THRESHOLD_PX = 48;

function formatOption(option: NseCompany): string {
  return `${option.name} (${option.ticker.replace(/\.NS$/, "")})`;
}

function matchesQueryLocally(option: NseCompany, rawQuery: string): boolean {
  const normalizedQuery = rawQuery.trim().toLowerCase();
  if (normalizedQuery.length === 0) {
    return true;
  }
  return (
    option.name.toLowerCase().includes(normalizedQuery) ||
    option.ticker.toLowerCase().includes(normalizedQuery)
  );
}

interface CompanyAutocompleteProps {
  label: string;
  value: NseCompany | null;
  onChange: (company: NseCompany | null) => void;
  /** Bearer token for GET /api/v1/companies/search. When null (auth still loading), this component skips the network search entirely and uses `fallbackOptions` -- see this file's own module docstring. */
  accessToken: string | null;
  /** Static offline/first-paint/search-failure fallback list. Defaults to NSE_TOP_50. */
  fallbackOptions?: readonly NseCompany[];
  error?: string;
  hint?: string;
}

export function CompanyAutocomplete({
  label,
  value,
  onChange,
  accessToken,
  fallbackOptions = NSE_TOP_50,
  error,
  hint,
}: CompanyAutocompleteProps): JSX.Element {
  const [rawQuery, setRawQuery] = useState(value ? formatOption(value) : "");
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);

  const debouncedQuery = useDebouncedValue(rawQuery, SEARCH_DEBOUNCE_MS);

  const [serverResults, setServerResults] = useState<NseCompany[]>([]);
  const [nextOffset, setNextOffset] = useState(0);
  const [hasMoreFromServer, setHasMoreFromServer] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [searchFailed, setSearchFailed] = useState(false);

  const inputId = useId();
  const listboxId = useId();
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;

  // (B5) Fires the first page of a fresh search whenever the debounced
  // query changes (including the very first time the dropdown opens,
  // with an empty query -- the full universe's first page). Skipped
  // entirely while accessToken is null; the render below falls back to
  // fallbackOptions in that case instead.
  useEffect(() => {
    if (!isOpen || accessToken === null) {
      if (accessToken === null) {
        setSearchFailed(true);
      }
      return undefined;
    }
    const token = accessToken;
    let cancelled = false;
    setIsSearching(true);
    setSearchFailed(false);

    async function runSearch(): Promise<void> {
      try {
        const page = await searchCompanies({
          accessToken: token,
          query: debouncedQuery,
          limit: SEARCH_PAGE_SIZE,
          offset: 0,
        });
        if (cancelled) return;
        setServerResults(
          page.items.map((item) => ({ name: item.name, ticker: item.ticker, exchange: "NSE" })),
        );
        setNextOffset(page.items.length);
        setHasMoreFromServer(page.has_more);
      } catch (caught) {
        if (!cancelled) {
          setSearchFailed(true);
          setServerResults([]);
          if (!(caught instanceof CompanyApiError)) {
            // Only an unexpected (non-API) failure is worth a console
            // trace -- a CompanyApiError (4xx/5xx from the backend) is
            // an ordinary, already-handled degrade-to-fallback case.
            console.error("CompanyAutocomplete: company search failed", caught);
          }
        }
      } finally {
        if (!cancelled) {
          setIsSearching(false);
        }
      }
    }

    void runSearch();
    return (): void => {
      cancelled = true;
    };
  }, [debouncedQuery, isOpen, accessToken]);

  async function loadMore(): Promise<void> {
    if (
      accessToken === null ||
      isSearching ||
      isLoadingMore ||
      searchFailed ||
      !hasMoreFromServer
    ) {
      return;
    }
    const token = accessToken;
    setIsLoadingMore(true);
    try {
      const page = await searchCompanies({
        accessToken: token,
        query: debouncedQuery,
        limit: SEARCH_PAGE_SIZE,
        offset: nextOffset,
      });
      setServerResults((previous) => [
        ...previous,
        ...page.items.map((item) => ({
          name: item.name,
          ticker: item.ticker,
          exchange: "NSE" as const,
        })),
      ]);
      setNextOffset((previous) => previous + page.items.length);
      setHasMoreFromServer(page.has_more);
    } catch {
      // Leave hasMoreFromServer as-is so a later scroll can retry --
      // the results already loaded remain fully usable either way.
    } finally {
      setIsLoadingMore(false);
    }
  }

  function handleListboxScroll(event: UIEvent<HTMLUListElement>): void {
    const target = event.currentTarget;
    const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
    if (distanceFromBottom < LOAD_MORE_THRESHOLD_PX) {
      void loadMore();
    }
  }

  const usingFallback = accessToken === null || searchFailed;

  const displayedOptions = useMemo(() => {
    if (usingFallback) {
      return fallbackOptions.filter((option) => matchesQueryLocally(option, rawQuery));
    }
    return serverResults;
  }, [usingFallback, fallbackOptions, rawQuery, serverResults]);

  function selectOption(option: NseCompany): void {
    onChange(option);
    setRawQuery(formatOption(option));
    setIsOpen(false);
  }

  function handleInputChange(newValue: string): void {
    setRawQuery(newValue);
    setIsOpen(true);
    setHighlightedIndex(0);
    if (value !== null) {
      onChange(null);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!isOpen) {
        setIsOpen(true);
        return;
      }
      setHighlightedIndex((index) => Math.min(index + 1, displayedOptions.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      const highlighted = displayedOptions[highlightedIndex];
      if (isOpen && highlighted) {
        event.preventDefault();
        selectOption(highlighted);
      }
    } else if (event.key === "Escape") {
      setIsOpen(false);
    }
  }

  const activeOptionId =
    isOpen && displayedOptions[highlightedIndex] ? `${listboxId}-${highlightedIndex}` : undefined;

  return (
    <div className="relative flex flex-col gap-1.5">
      <label htmlFor={inputId} className="text-sm font-medium text-ink">
        {label}
      </label>

      <div
        className={cn(
          "flex h-10 items-center rounded-card border bg-surface px-3 transition-colors",
          "focus-within:ring-2 focus-within:ring-brand-500 focus-within:ring-offset-2",
          "focus-within:ring-offset-canvas",
          error ? "border-verdict-sell" : "border-line",
        )}
      >
        <input
          id={inputId}
          role="combobox"
          aria-expanded={isOpen}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeOptionId}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : hint ? hintId : undefined}
          autoComplete="off"
          placeholder="Search NSE companies…"
          className={cn(
            "h-full w-full bg-transparent text-sm text-ink placeholder:text-muted",
            "focus:outline-none",
          )}
          value={rawQuery}
          onChange={(event) => handleInputChange(event.target.value)}
          onFocus={() => setIsOpen(true)}
          onBlur={() => setIsOpen(false)}
          onKeyDown={handleKeyDown}
        />
      </div>

      {error ? (
        <p id={errorId} role="alert" className="text-xs text-verdict-sell">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}

      {isOpen && (displayedOptions.length > 0 || isSearching) ? (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={label}
          onScroll={handleListboxScroll}
          className={cn(
            "absolute top-full z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-card border",
            "border-line bg-surface py-1 shadow-card",
          )}
        >
          {displayedOptions.map((option, index) => (
            <li
              key={option.ticker}
              id={`${listboxId}-${index}`}
              role="option"
              aria-selected={index === highlightedIndex}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setHighlightedIndex(index)}
              onClick={() => selectOption(option)}
              className={cn(
                "flex cursor-pointer items-baseline justify-between gap-3 px-3 py-2 text-sm",
                index === highlightedIndex ? "bg-brand-50 text-brand-700" : "text-ink",
              )}
            >
              <span>{option.name}</span>
              <span className="shrink-0 font-mono text-xs text-muted">{option.ticker}</span>
            </li>
          ))}

          {!usingFallback && (isSearching || isLoadingMore) ? (
            <li
              className="flex items-center gap-2 px-3 py-2 text-xs text-muted"
              role="status"
              aria-live="polite"
            >
              <Spinner size="sm" aria-hidden="true" />
              {isLoadingMore ? "Loading more…" : "Searching…"}
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}
