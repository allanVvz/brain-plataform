# Commercial branch contract

Canonical knowledge branch:

`Persona -> Brand -> Briefing? -> Campaign -> Audience -> ProductGroup? -> Product -> Offer? -> Copy? -> FAQ -> Embedded`

Asset branch:

`Brand|Campaign|ProductGroup|Product -> Asset -> Gallery`

- Anchor a FAQ at the lowest factual node available.
- Every FAQ needs a source, status, source node/type and branch path.
- A generated FAQ stays pending and has no Embedded edge.
- A human-approved FAQ has exactly one active projection to Embedded.
- Product, Copy, Offer and Persona never connect directly to Embedded.
- An Embedded projection does not erase or reparent the FAQ.

