-- Allow only the vector distance primitive used inside GraphRAG searches.
-- Table ownership remains unchanged; this migration grants no table access.

GRANT EXECUTE ON FUNCTION public.cosine_distance(vector, vector) TO brain_runtime;

NOTIFY pgrst, 'reload schema';
