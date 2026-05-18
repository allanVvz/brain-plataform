"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Package, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { ProductCard } from "@/components/products/ProductCard";
import { ProductMdModal } from "@/components/products/ProductMdModal";
import { LinkAssetDrawer } from "@/components/products/LinkAssetDrawer";

export default function ProdutosPage() {
  const [personaId, setPersonaId] = useState("");
  const [personaSlug, setPersonaSlug] = useState("");
  const [products, setProducts] = useState<any[]>([]);
  const [collections, setCollections] = useState<any[]>([]);
  const [categories, setCategories] = useState<any[]>([]);
  const [collection, setCollection] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedMd, setSelectedMd] = useState<any | null>(null);
  const [linkProduct, setLinkProduct] = useState<any | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function personaOpts() {
    return { persona_id: personaId || undefined, persona_slug: personaSlug || undefined };
  }

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const opts = personaOpts();
      const [productRows, collectionRows, categoryRows] = await Promise.all([
        api.products({ ...opts, collection_slug: collection || undefined, category_slug: category || undefined, status: status || undefined }),
        api.productCollections(opts),
        api.productCategories({ ...opts, collection_slug: collection || undefined }),
      ]);
      setProducts(productRows || []);
      setCollections(collectionRows || []);
      setCategories(categoryRows || []);
    } catch (err: any) {
      setError(err?.message || "Falha ao carregar produtos.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const savedId = window.localStorage.getItem("ai-brain-persona-id") || "";
    const savedSlug = window.localStorage.getItem("ai-brain-persona-slug") || "";
    setPersonaId(savedId);
    setPersonaSlug(savedSlug);
    const onPersonaChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string; slug?: string }>).detail;
      setPersonaId(detail?.id || "");
      setPersonaSlug(detail?.slug || "");
    };
    window.addEventListener("ai-brain-persona-change", onPersonaChange);
    return () => window.removeEventListener("ai-brain-persona-change", onPersonaChange);
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personaId, personaSlug, collection, category, status]);

  const counts = useMemo(() => {
    return {
      total: products.length,
      pending: products.filter((p) => p.status !== "validated").length,
      validated: products.filter((p) => p.status === "validated").length,
    };
  }, [products]);

  async function approve(product: any) {
    await api.approveProduct(product.slug, personaOpts());
    await load();
  }

  async function saveProduct(product: any, patch: any) {
    await api.updateProduct(product.slug, patch, personaOpts());
    await load();
  }

  async function sofia(product: any) {
    await api.sofiaSuggestProductImages(product.slug, { limit: 8, min_score: 0.15 }, personaOpts());
    await load();
  }

  async function newProduct() {
    if (!personaId && !personaSlug) {
      setError("Selecione uma persona no topo antes de criar produto.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      await api.createProduct({
        ...personaOpts(),
        title: "Novo Produto",
        summary: "Produto em preenchimento.",
        tags: ["produto"],
        collection_slug: collection || collections[0]?.slug,
        category_slug: category || categories[0]?.slug,
        status: "pending_validation",
        metadata: { source: "manual", created_from: "products_page" },
      });
      await load();
    } catch (err: any) {
      setError(err?.message || "Falha ao criar produto.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Package size={18} className="text-obs-violet" />
            <h1 className="text-lg font-semibold text-obs-text">Colecoes de Produtos</h1>
          </div>
          <p className="mt-0.5 text-xs text-obs-subtle">Produtos, categorias, assets e cards MD espelhados no Knowledge Graph.</p>
        </div>
        <button type="button" onClick={newProduct} disabled={creating} className="lg-btn lg-btn-primary rounded-lg">
          {creating ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Novo Produto
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="lg-card">
          <p className="text-[10px] uppercase tracking-wide text-obs-faint">Total</p>
          <p className="mt-1 text-2xl font-semibold text-obs-text">{counts.total}</p>
        </div>
        <div className="lg-card">
          <p className="text-[10px] uppercase tracking-wide text-obs-faint">Pendentes</p>
          <p className="mt-1 text-2xl font-semibold text-obs-amber">{counts.pending}</p>
        </div>
        <div className="lg-card">
          <p className="text-[10px] uppercase tracking-wide text-obs-faint">Validados</p>
          <p className="mt-1 text-2xl font-semibold text-green-400">{counts.validated}</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <select value={collection} onChange={(e) => { setCollection(e.target.value); setCategory(""); }} className="lg-input min-w-56 text-xs">
          <option value="">Todas colecoes</option>
          {collections.map((item) => <option key={item.id} value={item.slug}>{item.title}</option>)}
        </select>
        <select value={category} onChange={(e) => setCategory(e.target.value)} className="lg-input min-w-56 text-xs">
          <option value="">Todas categorias</option>
          {categories.map((item) => <option key={item.id} value={item.slug}>{item.title}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="lg-input min-w-48 text-xs">
          <option value="">Todos status</option>
          <option value="pending_validation">pending_validation</option>
          <option value="validated">validated</option>
        </select>
      </div>

      {error && <div className="rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</div>}
      {loading && <p className="flex items-center gap-2 text-sm text-obs-subtle"><Loader2 size={14} className="animate-spin" /> Carregando produtos...</p>}

      {!loading && products.length === 0 && (
        <div className="glass rounded-xl px-6 py-14 text-center text-sm text-obs-subtle">Nenhum produto encontrado.</div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {products.map((product) => (
          <ProductCard
            key={product.id}
            product={product}
            onOpenMd={() => setSelectedMd(product)}
            onApprove={() => approve(product)}
            onLinkAsset={() => setLinkProduct(product)}
            onSofia={() => sofia(product)}
          />
        ))}
      </div>

      {selectedMd && (
        <ProductMdModal
          product={selectedMd}
          onClose={() => setSelectedMd(null)}
          onSave={(patch) => saveProduct(selectedMd, patch)}
        />
      )}
      <LinkAssetDrawer
        open={Boolean(linkProduct)}
        personaId={personaId}
        product={linkProduct}
        onClose={() => setLinkProduct(null)}
        onLinked={load}
      />
    </div>
  );
}
