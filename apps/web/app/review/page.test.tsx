import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReviewPortal from "./page";

const item = {
  id: "review-1",
  release_id: "release-1",
  origin_table: "EmergencyRule",
  origin_row_id: "rule-1",
  content_hash: "a".repeat(64),
  evidence_summary: "Canonical evidence is available.",
  source_ids: ["source-1"],
  safety_critical: true,
  required_reviews: 2,
  status: "PENDING",
  claimed_by: null,
  claim_expires_at: null,
  version: 1,
};

describe("clinical review portal", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("loads the persistent queue and claims an item with its version", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response(JSON.stringify([item]), { status: 200 }))
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ ...item, status: "CLAIMED", claimed_by: "reviewer-1", version: 2 }),
            { status: 200 },
          ),
        ),
    );
    render(<ReviewPortal />);
    await screen.findByText("rule-1");
    fireEvent.click(screen.getByRole("button", { name: "Claim item" }));
    await screen.findByLabelText("Rationale bắt buộc");
    const call = vi.mocked(fetch).mock.calls[1];
    expect(call[0]).toContain("/review/workflow/items/review-1/claim");
    expect(JSON.parse(String((call[1] as RequestInit).body))).toMatchObject({ expected_version: 1 });
  });

  it("does not submit a decision without a substantive rationale", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify([{ ...item, status: "CLAIMED", claimed_by: "reviewer-1", version: 2 }]),
          { status: 200 },
        ),
      ),
    );
    render(<ReviewPortal />);
    await screen.findByLabelText("Rationale bắt buộc");
    fireEvent.change(screen.getByLabelText("Rationale bắt buộc"), { target: { value: "too short" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ít nhất 20 ký tự");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  });
});
