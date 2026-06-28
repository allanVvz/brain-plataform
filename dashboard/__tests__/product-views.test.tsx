import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { groupByProductGroup, productGroupLabel, NO_GROUP_LABEL } from "@/components/products/productGrouping";
import { ProductKanbanView } from "@/components/products/ProductKanbanView";
import { ProductListView } from "@/components/products/ProductListView";

afterEach(() => cleanup());

const products = [
  { id: "1", slug: "radar-1", title: "Radar 1", status: "pending_validation", metadata: { product_group: "Radar", source: "meta" } },
  { id: "2", slug: "radar-2", title: "Radar 2", status: "validated", metadata: { product_group: "Radar", source: "meta" } },
  { id: "3", slug: "juliet-1", title: "Juliet 1", status: "pending_validation", metadata: { product_group: "Juliet", source: "csv" } },
  { id: "4", slug: "loose-1", title: "Avulso", status: "pending_validation", metadata: { source: "manual" } },
];

describe("productGrouping", () => {
  it("labels a product by product_group with fallback to Sem grupo", () => {
    expect(productGroupLabel(products[0])).toBe("Radar");
    expect(productGroupLabel(products[3])).toBe(NO_GROUP_LABEL);
  });

  it("groups products and puts Sem grupo last", () => {
    const cols = groupByProductGroup(products);
    expect(cols.map((c) => c.group)).toEqual(["Radar", "Juliet", NO_GROUP_LABEL]);
    expect(cols[0].products).toHaveLength(2);
    expect(cols[cols.length - 1].group).toBe(NO_GROUP_LABEL);
  });
});

describe("ProductKanbanView", () => {
  it("renders one column per group plus a Sem grupo column", () => {
    render(<ProductKanbanView products={products} onOpenMd={() => {}} />);
    expect(screen.getByText("Radar")).toBeInTheDocument();
    expect(screen.getByText("Juliet")).toBeInTheDocument();
    expect(screen.getByText(NO_GROUP_LABEL)).toBeInTheDocument();
    // 4 product cards total
    expect(document.querySelectorAll("[data-kanban-card]")).toHaveLength(4);
  });
});

describe("ProductListView", () => {
  it("renders a row per product with source and group", () => {
    render(<ProductListView products={products} onOpenMd={() => {}} onApprove={() => {}} onLinkAsset={() => {}} />);
    expect(screen.getByText("Radar 1")).toBeInTheDocument();
    expect(screen.getAllByText("Radar").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("manual")).toBeInTheDocument();
  });

  it("calls onApprove for a pending product", () => {
    const onApprove = vi.fn();
    render(<ProductListView products={[products[0]]} onOpenMd={() => {}} onApprove={onApprove} onLinkAsset={() => {}} />);
    fireEvent.click(screen.getByTitle("Aprovar"));
    expect(onApprove).toHaveBeenCalledWith(products[0]);
  });
});
