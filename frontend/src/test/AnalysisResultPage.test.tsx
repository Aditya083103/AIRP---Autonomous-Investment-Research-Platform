// frontend/src/test/AnalysisResultPage.test.tsx
// Tests for AnalysisResultPage (T-057): renders honest "coming soon"
// copy and shows the job_id from the route params.

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AnalysisResultPage } from "@/pages/AnalysisResultPage";

describe("AnalysisResultPage", () => {
  it("renders a coming-soon heading and the job_id from the route", () => {
    render(
      <MemoryRouter initialEntries={["/analysis/abc-123/result"]}>
        <Routes>
          <Route path="/analysis/:jobId/result" element={<AnalysisResultPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: /results page is being built/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("abc-123")).toBeInTheDocument();
  });
});
