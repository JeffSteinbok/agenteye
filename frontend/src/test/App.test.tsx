import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import App from "../components/App";

describe("App", () => {
  it("renders the dashboard header", () => {
    render(<App />);
    expect(screen.getByText("AI CLI Agent Dashboard")).toBeInTheDocument();
  });

  it("shows the Active tab by default", () => {
    render(<App />);
    expect(screen.getByText(/Active/)).toBeInTheDocument();
  });
});
