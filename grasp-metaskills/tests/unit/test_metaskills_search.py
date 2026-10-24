"""Additional boundary coverage plus ports of named upstream tests at pinned MIT commit."""

import math

from grasp_metaskills.metaskills_search import (
    HashEmbeddingProvider,
    HybridResult,
    RrfConfig,
    SearchFilters,
    VectorIndex,
    cosine_similarity,
    f32,
    filter_hybrid_results,
    filter_skill_ids,
    fuse_results,
    fuse_with_limit,
    hash_embedding,
    parse_tags_from_metadata,
    tokenize,
)


def test_embedding_dimensions_normalized_empty_and_single_char_tokens():
    # embeddings.rs::test_embedding_{dimensions,normalized,empty_input,single_char_tokens}
    v = hash_embedding("semantic search for skills", 128)
    assert len(v) == 128
    assert abs(math.sqrt(sum(x * x for x in v)) - 1) < 1e-3
    assert hash_embedding("   ", 32) == [0.0] * 32
    assert any(hash_embedding("a b c d", 32))
    assert hash_embedding("anything", 0) == []
    assert tokenize("C programming C++ C#") == ["c", "programming", "c++", "c#"]
    assert tokenize("a\u0345") == ["a\u0345"]  # Alphabetic combining mark in Rust


def test_upstream_similarity_prefers_related_text_and_vector_index_search():
    a = hash_embedding("git commit workflow", 64)
    assert cosine_similarity(a, hash_embedding("git commit messages", 64)) > cosine_similarity(
        a, hash_embedding("quantum entanglement photons", 64)
    )
    assert cosine_similarity([0], [1]) == 0
    assert cosine_similarity([1], [1, 2]) == 0
    index = VectorIndex(128)
    assert index.insert("git", hash_embedding("git commit workflow repository version", 128))
    index.insert("rust", hash_embedding("rust error handling compile memory safety", 128))
    assert index.search(hash_embedding("git commit workflow", 128), 1)[0][0] == "git"
    assert not index.insert("bad", [1])
    assert index.search([1], 1) == []
    assert index.remove("git") is not None
    assert index.remove("missing") is None
    assert HashEmbeddingProvider(8).embed(["git", "rust"]) == [
        hash_embedding("git", 8),
        hash_embedding("rust", 8),
    ]


def test_upstream_fusion_boosts_agreement_preserves_scores_and_duplicates():
    rows = fuse_results([("s1", 5), ("s2", 3), ("s3", 2)], [("s1", 0.95), ("s3", 0.8), ("s4", 0.7)])
    assert rows[0].skill_id == "s1"
    assert rows[0].bm25_score == 5
    assert rows[0].semantic_score == f32(0.95)
    assert fuse_results([], []) == []
    repeated = fuse_results([("s", 5), ("s", 3)], [])[0]
    assert repeated.bm25_rank == 2 and repeated.bm25_score == 3
    assert repeated.score == f32(f32(1 / 61) + f32(1 / 62))
    assert len(fuse_with_limit([("a", 1)], [("b", 1)], RrfConfig(), 1)) == 1


def test_upstream_filter_defaults_any_match_quality_aliases_and_metadata():
    # context.rs::test_{matches_combined_filters,min_quality_clamped,filters_is_empty}
    assert not SearchFilters().is_empty()
    assert SearchFilters(include_deprecated=True).is_empty()
    assert SearchFilters(min_quality=1.5).min_quality == 1
    assert SearchFilters(min_quality=-0.5).min_quality == 0
    filters = SearchFilters(tags=["rust", "cli"], layer="global", min_quality=0.7)
    assert filters.matches(["rust"], "org", 0.7, False)
    assert not filters.matches(["Rust"], "org", 0.8, False)
    assert not filters.matches(["cli"], "project", 0.8, False)
    assert not filters.matches(["cli"], "org", 0.69, False)
    assert not filters.matches(["cli"], "org", 0.8, True)
    assert SearchFilters.parse_tags(" Git, , Rust ") == ["git", "rust"]
    assert parse_tags_from_metadata('{"tags":["RUST",1]}') == ["rust"]
    assert parse_tags_from_metadata("not json") == []
    assert parse_tags_from_metadata("[]") == []
    records = {
        "ok": dict(
            metadata_json='{"tags":["Rust"]}',
            source_layer="global",
            quality_score=0.8,
            is_deprecated=False,
        )
    }
    assert filter_skill_ids(["missing", "ok"], filters, records.get) == ["ok"]
    result = HybridResult("ok", 0.2)
    assert filter_hybrid_results([HybridResult("missing", 1), result], filters, records.get) == [
        result
    ]
