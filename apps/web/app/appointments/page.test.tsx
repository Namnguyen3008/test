import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Appointments from "./page";

describe("appointments portal", () => {
  afterEach(() => vi.restoreAllMocks());
  it("loads real history and availability contracts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ items: [] }), { status: 200 })).mockResolvedValueOnce(new Response(JSON.stringify({ items: [] }), { status: 200 })));
    render(<Appointments />);
    expect(screen.getByText("Đang tải lịch hẹn…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Chưa có lịch hẹn")).toBeInTheDocument());
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("renders an explicit expired-session state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Authentication required" }), { status: 401 })));
    render(<Appointments />);
    await waitFor(() => expect(screen.getByText(/Phiên đăng nhập đã hết hạn/)).toBeInTheDocument());
  });
});
