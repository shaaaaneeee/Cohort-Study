import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

const REPLY = `Done — here's the updated study:
**Exposure:** Programme A participants
**Population:**
- Age 18+
- Included only if: diagnosed with *diabetes*

Please review it.`;

describe("Markdown", () => {
  it("shows bold, italics and lists without the asterisks", () => {
    const { container } = render(<Markdown text={REPLY} />);
    expect(container.textContent).not.toContain("*");
    expect(screen.getByText("Exposure:").tagName).toBe("STRONG");
    expect(screen.getByText("diabetes").tagName).toBe("EM");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Please review it.")).toBeTruthy();
  });

  it("renders text as text, not HTML", () => {
    const { container } = render(<Markdown text={"<b>hi</b>"} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toBe("<b>hi</b>");
  });
});

describe("Markdown line breaks", () => {
  it("keeps single line breaks", () => {
    const { container } = render(<Markdown text={"**A:** one\n**B:** two"} />);
    expect(container.querySelectorAll("br")).toHaveLength(1);
  });
});
