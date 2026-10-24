"""Golden source: MetaSkills dcd3fb55cabb438dc200f9b7c784ca14c08135ce.

embeddings.rs::{HashEmbedder::embed,test_fnv1a_hash_known_value};
hybrid.rs::{test_rrf_score_calculation,test_weighted_fusion}.
Vectors captured from unmodified Rust functions in an offline rustc harness.
"""

import pytest

from grasp_metaskills.metaskills_search import (
    RrfConfig,
    f32,
    fnv1a_hash,
    fuse_results,
    hash_embedding,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "git commit workflow",
            [
                0.20871884,
                -0.4684707,
                0.20871885,
                -0.039634146,
                0.09459979,
                0.7039198,
                -0.33423674,
                0.27508327,
            ],
        ),
        (
            "C++ C# R",
            [
                0.038870182,
                -0.8507257,
                0.03887019,
                0.14347723,
                0.038870182,
                0.14347719,
                -0.45823127,
                0.1434772,
            ],
        ),
        (
            "你好 Rust",
            [
                -0.49753815,
                0.18553059,
                0.59565216,
                -0.31869534,
                0.11155966,
                -0.0040796907,
                0.40604186,
                0.2904025,
            ],
        ),
        ("   ", [0.0] * 8),
    ],
)
def test_rust_hash_embedding_golden(text, expected):
    assert hash_embedding(text, 8) == [f32(x) for x in expected]


def test_upstream_fnv_known_value():
    assert fnv1a_hash(b"hello") == 0xA430D84680AABD0B


def test_upstream_rrf_score_calculation():
    result = fuse_results([("skill-1", 5.0)], [("skill-1", 0.9)])[0]
    assert result.score == f32(2 * f32(1 / 61))
    assert (result.bm25_rank, result.semantic_rank) == (1, 1)


def test_upstream_weighted_fusion():
    result = fuse_results(
        [("bm25-winner", 5)], [("semantic-winner", 0.9)], RrfConfig(bm25_weight=2)
    )
    assert result[0].skill_id == "bm25-winner"
