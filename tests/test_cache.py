from router.cache import ExactCache, SemanticCache, cosine, embed, normalize


def test_normalize_strips_case_punct_space():
    assert normalize("  How DO I  reset, my password?? ") == "how do i reset my password"


def test_exact_cache_hit_after_normalization_and_ttl_expiry():
    t = [0.0]
    c = ExactCache(ttl_s=10, clock=lambda: t[0])
    c.put("Reset password?", "A")
    assert c.get("reset   PASSWORD") == "A"
    t[0] = 11
    assert c.get("reset password") is None and c.misses == 1


def test_exact_cache_lru_eviction():
    c = ExactCache(max_items=2)
    c.put("a", "1"); c.put("b", "2"); c.get("a"); c.put("c", "3")
    assert c.get("b") is None and c.get("a") == "1" and c.get("c") == "3"


def test_embedding_is_unit_norm_and_similar_texts_score_higher():
    a, b, z = embed("how do i reset my password"), embed("how can i reset my password"), embed("best pizza in chicago")
    assert abs(cosine(a, a) - 1) < 1e-9
    assert cosine(a, b) > 0.8 > cosine(a, z)


def test_semantic_cache_threshold():
    s = SemanticCache(threshold=0.8)
    s.put("how do i reset my password", "reset via settings")
    hit = s.get("how can i reset my password?")
    assert hit and hit[0] == "reset via settings" and hit[1] >= 0.8
    assert s.get("what is the refund policy for shoes") is None
