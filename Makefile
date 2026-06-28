.PHONY: test-bra-4

test-bra-4:
	python -m pytest -q tests/e2e/test_vzlupas_catalog_to_hierarchical_graph_e2e.py
