// Shared grouping helpers for the Lista/Kanban views of /marketing/produtos.

export const NO_GROUP_LABEL = "Sem grupo";

/** Resolve the product_group label for a product, with sensible fallbacks. */
export function productGroupLabel(product: any): string {
  const meta = product?.metadata || {};
  return (
    meta.product_group ||
    product?.collection?.title ||
    meta.collection_slug ||
    product?.collection_slug ||
    NO_GROUP_LABEL
  );
}

export type ProductGroupColumn = { group: string; products: any[] };

/**
 * Group products by product_group for the Kanban. Products without a group go
 * into a trailing "Sem grupo" column. Real groups keep first-seen order.
 */
export function groupByProductGroup(products: any[]): ProductGroupColumn[] {
  const columns = new Map<string, any[]>();
  const order: string[] = [];
  for (const product of products || []) {
    const group = productGroupLabel(product);
    if (!columns.has(group)) {
      columns.set(group, []);
      order.push(group);
    }
    columns.get(group)!.push(product);
  }
  // Ensure "Sem grupo" is always last when present.
  order.sort((a, b) => (a === NO_GROUP_LABEL ? 1 : b === NO_GROUP_LABEL ? -1 : 0));
  return order.map((group) => ({ group, products: columns.get(group)! }));
}
