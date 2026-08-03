import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import PatientHome from "./page";

describe("patient portal", () => {
  it("shows the emergency action before the chat form", () => {
    render(<PatientHome />);
    const emergency = screen.getByText("Trường hợp khẩn cấp");
    const input = screen.getByLabelText("Mô tả tình trạng");
    expect(emergency.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("115")).toBeInTheDocument();
  });
});
