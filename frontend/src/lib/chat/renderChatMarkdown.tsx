// frontend/src/lib/chat/renderChatMarkdown.tsx
// AIRP -- Minimal markdown rendering for AIRP Assistant replies
//
// Bug fix: backend.services.chat_llm.SYSTEM_PROMPT explicitly asks the
// model for "a short bullet list" (RESPONSE_STYLE_INSTRUCTIONS["concise"]),
// and LLMs routinely add **bold** emphasis around figures/verdicts even
// without being asked -- but ChatMessageBubble.tsx rendered every reply
// as inert plain text (`whitespace-pre-line`), so a real reply like
// "- **BUY** rating: Rs. 1,058" showed up to the user exactly like that,
// literal asterisks and dashes included, instead of a formatted bullet
// with bold text.
//
// Deliberately NOT a full CommonMark implementation and NOT a new
// dependency (react-markdown's remark/rehype/unified tree is a lot of
// bundle weight -- this app's build already warns about chunk size --
// for a narrow need: short chat replies using bold/italic/inline-code
// emphasis and simple bullet/numbered lists, never tables, images, or
// nested blockquotes). Renders directly to React elements, never
// dangerouslySetInnerHTML, so there is no HTML-injection surface from
// model-generated text.
//
// Only ChatMessageBubble.tsx's ASSISTANT bubbles call this -- a user's
// own typed message is shown as the literal text they typed, matching
// every mainstream chat product's convention (your own "*" is not
// silently reinterpreted as markdown).

import { Fragment, type ReactNode } from "react";

import { cn } from "@/lib/cn";

const _INLINE_PATTERN = /(\*\*(.+?)\*\*|`([^`]+)`|\*(?!\*)([^*]+?)\*)/g;

/** Bold / inline-code / italic within one line -- applied after block splitting. */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let index = 0;
  let match: RegExpExecArray | null;

  _INLINE_PATTERN.lastIndex = 0;
  while ((match = _INLINE_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(
        <Fragment key={`${keyPrefix}-t-${index++}`}>{text.slice(lastIndex, match.index)}</Fragment>,
      );
    }
    if (match[2] !== undefined) {
      nodes.push(<strong key={`${keyPrefix}-b-${index++}`}>{match[2]}</strong>);
    } else if (match[3] !== undefined) {
      nodes.push(
        <code
          key={`${keyPrefix}-c-${index++}`}
          className="rounded bg-line px-1 py-0.5 font-mono text-[0.85em] text-ink"
        >
          {match[3]}
        </code>,
      );
    } else if (match[4] !== undefined) {
      nodes.push(<em key={`${keyPrefix}-i-${index++}`}>{match[4]}</em>);
    }
    lastIndex = _INLINE_PATTERN.lastIndex;
  }
  if (lastIndex < text.length) {
    nodes.push(<Fragment key={`${keyPrefix}-t-${index++}`}>{text.slice(lastIndex)}</Fragment>);
  }
  return nodes;
}

const _BULLET_RE = /^[-*]\s+(.*)$/;
const _NUMBERED_RE = /^\d+\.\s+(.*)$/;

/**
 * Render a chat reply's markdown-lite content -- paragraphs (blank-line
 * separated, single newlines within one become a line break), unordered
 * ("-"/"*") and ordered ("1.") lists, and bold/italic/code inline
 * emphasis (double-asterisk, single-asterisk, backtick respectively).
 */
export function renderChatMarkdown(content: string): ReactNode {
  const lines = content.split("\n");
  const blocks: ReactNode[] = [];
  let paragraphLines: string[] = [];
  let listItems: string[] = [];
  let listOrdered = false;
  let blockKey = 0;

  function flushParagraph(): void {
    if (paragraphLines.length === 0) {
      return;
    }
    const withBreaks: ReactNode[] = [];
    paragraphLines.forEach((line, idx) => {
      if (idx > 0) {
        withBreaks.push(<br key={`br-${blockKey}-${idx}`} />);
      }
      withBreaks.push(...renderInline(line, `p-${blockKey}-${idx}`));
    });
    blocks.push(
      <p key={`p-${blockKey++}`} className="mb-2 last:mb-0">
        {withBreaks}
      </p>,
    );
    paragraphLines = [];
  }

  function flushList(): void {
    if (listItems.length === 0) {
      return;
    }
    const items = listItems.map((item, idx) => (
      <li key={idx}>{renderInline(item, `li-${blockKey}-${idx}`)}</li>
    ));
    blocks.push(
      listOrdered ? (
        <ol key={`list-${blockKey++}`} className="mb-2 list-decimal space-y-0.5 pl-5 last:mb-0">
          {items}
        </ol>
      ) : (
        <ul key={`list-${blockKey++}`} className={cn("mb-2 list-disc space-y-0.5 pl-5 last:mb-0")}>
          {items}
        </ul>
      ),
    );
    listItems = [];
  }

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.length === 0) {
      flushParagraph();
      flushList();
      continue;
    }

    const bulletMatch = _BULLET_RE.exec(trimmed);
    const numberedMatch = _NUMBERED_RE.exec(trimmed);

    if (bulletMatch) {
      flushParagraph();
      if (listOrdered) {
        flushList();
      }
      listOrdered = false;
      listItems.push(bulletMatch[1] ?? "");
      continue;
    }

    if (numberedMatch) {
      flushParagraph();
      if (!listOrdered) {
        flushList();
      }
      listOrdered = true;
      listItems.push(numberedMatch[1] ?? "");
      continue;
    }

    flushList();
    paragraphLines.push(line);
  }
  flushParagraph();
  flushList();

  return <>{blocks}</>;
}
