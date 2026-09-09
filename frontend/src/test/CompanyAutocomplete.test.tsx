// frontend/src/test/CompanyAutocomplete.test.tsx
// Tests for CompanyAutocomplete (T-058, rewired B5).
//
// Two halves, matching the component's two modes:
//   1. Fallback mode (accessToken=null) -- exercises the same
//      local-filter/keyboard-nav/click-to-select behaviour the T-058
//      version of this component always had, now reached by passing
//      no token rather than by being the component's only mode.
//   2. Server mode (accessToken set, global.fetch stubbed) -- the B5
//      behaviour: debounced GET /api/v1/companies/search, rendering
//      the response, degrading to fallbackOptions on a request
//      failure, and loading a further page via scroll (a scroll event
//      with jsdom's scroll geometry properties stubbed, the standard
//      way to simulate "scrolled near the bottom" in a jsdom test).

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompanyAutocomplete } from "@/components/analysis/CompanyAutocomplete";
import { type NseCompany } from "@/data/nseTop50";

const OPTIONS: NseCompany[] = [
  { name: "Infosys", ticker: "INFY.NS", exchange: "NSE" },
  { name: "Tata Consultancy Services", ticker: "TCS.NS", exchange: "NSE" },
  { name: "ICICI Bank", ticker: "ICICIBANK.NS", exchange: "NSE" },
];

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function searchResponse(
  items: { name: string; ticker: string }[],
  overrides: Record<string, unknown> = {},
): unknown {
  return {
    items: items.map((item) => ({ ...item, exchange: "NSE" })),
    total_count: items.length,
    limit: 30,
    offset: 0,
    has_more: false,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CompanyAutocomplete fallback mode (accessToken=null)", () => {
  it("shows options when the input is focused", async () => {
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken={null}
        fallbackOptions={OPTIONS}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Company" }));

    expect(screen.getByRole("option", { name: /infosys/i })).toBeInTheDocument();
  });

  it("filters options by name as the user types", async () => {
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken={null}
        fallbackOptions={OPTIONS}
      />,
    );

    await user.type(screen.getByRole("combobox", { name: "Company" }), "infosys");

    expect(screen.getByRole("option", { name: /infosys/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /tata consultancy/i })).not.toBeInTheDocument();
  });

  it("filters options by ticker as the user types", async () => {
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken={null}
        fallbackOptions={OPTIONS}
      />,
    );

    await user.type(screen.getByRole("combobox", { name: "Company" }), "TCS");

    expect(screen.getByRole("option", { name: /tata consultancy/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /infosys/i })).not.toBeInTheDocument();
  });

  it("calls onChange with the full company object when an option is clicked", async () => {
    const handleChange = vi.fn();
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={handleChange}
        accessToken={null}
        fallbackOptions={OPTIONS}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Company" }));
    await user.click(screen.getByRole("option", { name: /infosys/i }));

    expect(handleChange).toHaveBeenCalledWith(OPTIONS[0]);
  });

  it("selects the highlighted option on Enter", async () => {
    const handleChange = vi.fn();
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={handleChange}
        accessToken={null}
        fallbackOptions={OPTIONS}
      />,
    );

    const input = screen.getByRole("combobox", { name: "Company" });
    await user.click(input);
    await user.keyboard("{ArrowDown}{Enter}");

    expect(handleChange).toHaveBeenCalledWith(OPTIONS[1]);
  });

  it("shows a validation error message when given one", () => {
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken={null}
        fallbackOptions={OPTIONS}
        error="Select a company from the list."
      />,
    );

    expect(screen.getByText("Select a company from the list.")).toBeInTheDocument();
  });

  it("defaults fallbackOptions to NSE_TOP_50 when not provided", async () => {
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete label="Company" value={null} onChange={vi.fn()} accessToken={null} />,
    );

    await user.type(screen.getByRole("combobox", { name: "Company" }), "reliance");

    expect(screen.getByRole("option", { name: /reliance/i })).toBeInTheDocument();
  });
});

describe("CompanyAutocomplete server mode (accessToken set)", () => {
  it("queries GET /api/v1/companies/search with the debounced text and renders the results", async () => {
    // mockImplementation (a fresh Response per call), not
    // mockResolvedValue (one Response instance reused for every call)
    // -- opening the combobox fires an empty-query search AND typing
    // fires a second, debounced "infy" search; a Response body can
    // only be read once, so sharing one instance across both calls
    // would throw on the second .json() read.
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          jsonResponse(200, searchResponse([{ name: "Infosys", ticker: "INFY.NS" }])),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken="jwt-token"
      />,
    );

    await user.type(screen.getByRole("combobox", { name: "Company" }), "infy");

    // Two requests happen in practice: one for the empty query fired
    // the moment the combobox opens (typing focuses it first), and
    // one for the debounced "infy" query once typing settles -- find
    // the query-specific call rather than assuming it is the last one
    // recorded, since both resolve to the same canned response and
    // waitFor below can settle before the second call lands.
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /infosys/i })).toBeInTheDocument(),
    );
    await waitFor(() => {
      const calls = fetchMock.mock.calls as [string, RequestInit][];
      expect(calls.some(([url]) => url.includes("q=infy"))).toBe(true);
    });

    const calls = fetchMock.mock.calls as [string, RequestInit][];
    const queryCall = calls.find(([url]) => url.includes("q=infy"));
    const [url, options] = queryCall as [string, RequestInit];
    expect(url).toContain("/companies/search");
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-token");
  });

  it("fetches the full universe's first page when opened with an empty query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        200,
        searchResponse(
          [
            { name: "HDFC Bank", ticker: "HDFCBANK.NS" },
            { name: "ICICI Bank", ticker: "ICICIBANK.NS" },
          ],
          { total_count: 269, has_more: true },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken="jwt-token"
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Company" }));

    await waitFor(() =>
      expect(screen.getByRole("option", { name: /hdfc bank/i })).toBeInTheDocument(),
    );
  });

  it("shows a searching indicator while the request is in flight", async () => {
    let resolveFetch: (value: Response) => void = () => {};
    const fetchMock = vi.fn().mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken="jwt-token"
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Company" }));

    await waitFor(() => expect(screen.getByText(/searching/i)).toBeInTheDocument());

    resolveFetch(jsonResponse(200, searchResponse([])));
    await waitFor(() => expect(screen.queryByText(/searching/i)).not.toBeInTheDocument());
  });

  it("falls back to fallbackOptions when the search request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken="jwt-token"
        fallbackOptions={OPTIONS}
      />,
    );

    await user.type(screen.getByRole("combobox", { name: "Company" }), "infosys");

    await waitFor(() =>
      expect(screen.getByRole("option", { name: /infosys/i })).toBeInTheDocument(),
    );
  });

  it("falls back to fallbackOptions when the search request returns a 500", async () => {
    // mockImplementation, not mockResolvedValue -- see the debounced-
    // text test above for why a fresh Response per call matters here
    // too (this test's own user.type() also produces two calls).
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(jsonResponse(500, { detail: "Internal Server Error" })),
        ),
    );

    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken="jwt-token"
        fallbackOptions={OPTIONS}
      />,
    );

    await user.type(screen.getByRole("combobox", { name: "Company" }), "tcs");

    await waitFor(() =>
      expect(screen.getByRole("option", { name: /tata consultancy/i })).toBeInTheDocument(),
    );
  });

  it("loads a further page when the listbox is scrolled near its bottom", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          200,
          searchResponse([{ name: "HDFC Bank", ticker: "HDFCBANK.NS" }], {
            total_count: 2,
            has_more: true,
          }),
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          200,
          searchResponse([{ name: "ICICI Bank", ticker: "ICICIBANK.NS" }], {
            offset: 1,
            total_count: 2,
            has_more: false,
          }),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        accessToken="jwt-token"
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Company" }));
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /hdfc bank/i })).toBeInTheDocument(),
    );

    const listbox = screen.getByRole("listbox");
    Object.defineProperty(listbox, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(listbox, "clientHeight", { value: 300, configurable: true });
    Object.defineProperty(listbox, "scrollTop", { value: 690, configurable: true });
    listbox.dispatchEvent(new Event("scroll", { bubbles: true }));

    await waitFor(() =>
      expect(screen.getByRole("option", { name: /icici bank/i })).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const calls = fetchMock.mock.calls as [string, RequestInit][];
    const secondCallUrl = calls[1]?.[0];
    expect(secondCallUrl).toContain("offset=1");
  });

  it("does not call onChange with a stale selection when accessToken becomes available mid-session", () => {
    // Regression guard: switching from fallback mode to server mode
    // (e.g. accessToken finishes loading) must not clear an
    // already-made selection out from under the caller.
    const handleChange = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, searchResponse([]))));

    const { rerender } = render(
      <CompanyAutocomplete
        label="Company"
        value={OPTIONS[0] ?? null}
        onChange={handleChange}
        accessToken={null}
        fallbackOptions={OPTIONS}
      />,
    );

    rerender(
      <CompanyAutocomplete
        label="Company"
        value={OPTIONS[0] ?? null}
        onChange={handleChange}
        accessToken="jwt-token"
        fallbackOptions={OPTIONS}
      />,
    );

    expect(handleChange).not.toHaveBeenCalled();
  });
});
