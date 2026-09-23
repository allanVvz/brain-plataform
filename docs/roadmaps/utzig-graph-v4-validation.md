# Utzig GraphBundle v4 validation — 2026-09-23

The exact quality failure was reproduced and isolated. The customer sent
`Onix`; the reply acknowledged `Onix`, but the ledger did not accept
`modelo_veiculo`. The field already existed in the graph, but its validation
metadata was only `mode=schema`.

GraphBundle v4 added semantic graph guidance for `modelo_veiculo` (vehicle
model examples including Onix, Civic, Corolla and Gol) and `vehicle_color`.
No nodes or edges were added; 12 product nodes changed, with 128 chunks
reused and no new embeddings.

Active publication:

- publication: `c36ccfdb-4758-49f8-9190-80b408246cff`
- version: `4`
- checksum: `sha256:8867fb1dba3836e4fedea60708d747137368d53202b38be280454ad23805036c`

Internal Validator session `bcbc8e84-84fa-4c0e-957a-6a7170e28d24` proved the
graph correction through three turns: `modelo_veiculo` and `condicao` were
accepted, every semantic criterion passed, and each turn had one proof and one
completed commit. The final turn then hit the pre-existing runtime failure
`Transport worker did not persist the canonical turn result`; the runtime
remained on the rolled-back blue digest.
