// frontend/src/test/renderChatMarkdown.test.tsx
// Tests for the AIRP Assistant reply formatter (bug fix): chat replies
// used to render as inert plain text, so a real reply's "- **BUY**
// rating" showed the literal asterisks/dashes instead of a formatted
// bullet with bold text. Covers bold/italic/inline-code emphasis,
// unordered and ordered lists, paragraph breaks, and mixed content.

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderChatMarkdown } from "@/lib/chat/renderChatMarkdown";

describe("renderChatMarkdown", () => {
  it("renders **bold** text as a <strong> element", () => {
    const { container } = render(<>{renderChatMarkdown("The verdict is **BUY**.")}</>);
    const strong = container.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong?.textContent).toBe("BUY");
    expect(container.textContent).toBe("The verdict is BUY.");
  });

  it("renders *italic* text as an <em> element", () => {
    const { container } = render(<>{renderChatMarkdown("This is *emphasised*.")}</>);
    expect(container.querySelector("em")?.textContent).toBe("emphasised");
  });

  it("renders `code` spans as a <code> element", () => {
    const { container } = render(<>{renderChatMarkdown("Look up `TCS.NS` for details.")}</>);
    expect(container.querySelector("code")?.textContent).toBe("TCS.NS");
  });

  it("renders a bullet list as a real <ul>/<li> structure, not literal dashes", () => {
    const content = "Key risks:\n- Revenue concentration\n- Talent attrition";
    const { container } = render(<>{renderChatMarkdown(content)}</>);
    const list = container.querySelector("ul");
    expect(list).not.toBeNull();
    const items = list ? Array.from(list.querySelectorAll("li")).map((li) => li.textContent) : [];
    expect(items).toEqual(["Revenue concentration", "Talent attrition"]);
    expect(container.textContent).not.toContain("- Revenue");
  });

  it("renders a numbered list as a real <ol>/<li> structure", () => {
    const content = "1. First step\n2. Second step";
    const { container } = render(<>{renderChatMarkdown(content)}</>);
    const list = container.querySelector("ol");
    expect(list).not.toBeNull();
    const items = list ? Array.from(list.querySelectorAll("li")).map((li) => li.textContent) : [];
    expect(items).toEqual(["First step", "Second step"]);
  });

  it("separates blank-line paragraphs into distinct <p> elements", () => {
    const content = "First paragraph.\n\nSecond paragraph.";
    const { container } = render(<>{renderChatMarkdown(content)}</>);
    const paragraphs = Array.from(container.querySelectorAll("p"));
    expect(paragraphs.map((p) => p.textContent)).toEqual(["First paragraph.", "Second paragraph."]);
  });

  it("keeps a single newline within one paragraph as a line break", () => {
    const content = "Line one.\nLine two.";
    const { container } = render(<>{renderChatMarkdown(content)}</>);
    expect(container.querySelectorAll("p")).toHaveLength(1);
    expect(container.querySelector("br")).not.toBeNull();
  });

  it("handles a realistic mixed reply (paragraph + bold + list)", () => {
    const content =
      "AIRP rated **Infosys** a HOLD with conviction 4/10.\n\nKey risks:\n- Revenue concentration\n- Talent attrition";
    const { container } = render(<>{renderChatMarkdown(content)}</>);
    expect(container.querySelector("strong")?.textContent).toBe("Infosys");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.textContent).not.toContain("**");
  });
});
