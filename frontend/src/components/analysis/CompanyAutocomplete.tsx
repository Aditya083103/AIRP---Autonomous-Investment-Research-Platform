// frontend/src/components/analysis/CompanyAutocomplete.tsx
// AIRP -- Company autocomplete combobox (T-058)
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

import { useId, useMemo, useState, type KeyboardEvent } from "react";

import { type NseCompany } from "@/data/nseTop50";
import { cn } from "@/lib/cn";

const MAX_VISIBLE_OPTIONS = 8;

function formatOption(option: NseCompany): string {
  return `${option.name} (${option.ticker.replace(/\.NS$/, "")})`;
}

interface CompanyAutocompleteProps {
  label: string;
  value: NseCompany | null;
  onChange: (company: NseCompany | null) => void;
  options: readonly NseCompany[];
  error?: string;
  hint?: string;
}

export function CompanyAutocomplete({
  label,
  value,
  onChange,
  options,
  error,
  hint,
}: CompanyAutocompleteProps): JSX.Element {
  const [query, setQuery] = useState(value ? formatOption(value) : "");
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);

  const inputId = useId();
  const listboxId = useId();
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;

  const filteredOptions = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const matches =
      normalizedQuery.length === 0
        ? options
        : options.filter(
            (option) =>
              option.name.toLowerCase().includes(normalizedQuery) ||
              option.ticker.toLowerCase().includes(normalizedQuery),
          );
    return matches.slice(0, MAX_VISIBLE_OPTIONS);
  }, [query, options]);

  function selectOption(option: NseCompany): void {
    onChange(option);
    setQuery(formatOption(option));
    setIsOpen(false);
  }

  function handleInputChange(newValue: string): void {
    setQuery(newValue);
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
      setHighlightedIndex((index) => Math.min(index + 1, filteredOptions.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      const highlighted = filteredOptions[highlightedIndex];
      if (isOpen && highlighted) {
        event.preventDefault();
        selectOption(highlighted);
      }
    } else if (event.key === "Escape") {
      setIsOpen(false);
    }
  }

  const activeOptionId =
    isOpen && filteredOptions[highlightedIndex] ? `${listboxId}-${highlightedIndex}` : undefined;

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
          value={query}
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

      {isOpen && filteredOptions.length > 0 ? (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={label}
          className={cn(
            "absolute top-full z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-card border",
            "border-line bg-surface py-1 shadow-card",
          )}
        >
          {filteredOptions.map((option, index) => (
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
        </ul>
      ) : null}
    </div>
  );
}
