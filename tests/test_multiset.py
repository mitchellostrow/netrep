"""
Tests metrics between network representations.
"""
import pytest
import numpy as np
from scipy.spatial.distance import pdist
from sklearn.utils.validation import check_random_state
import netrep.metrics
from netrep.multiset import pairwise_distances, frechet_mean

TOL = 1e-6


@pytest.mark.parametrize('seed', [1, 2, 3])
@pytest.mark.parametrize('metricname', ['LinearMetric', 'PermutationMetric'])
@pytest.mark.parametrize('m', [100])
@pytest.mark.parametrize('n', [10])
@pytest.mark.parametrize('num_X', [4])
def test_pairwise_caching(seed, metricname, m, n, num_X):

    # Set random seed, draw random rotation.
    rs = check_random_state(seed)
    Xs = [rs.randn(m, n) for _ in range(num_X)]

    # Specify metric.
    metric = getattr(netrep.metrics, metricname)()

    # Compute pairwise distances with caching.
    D1 = pairwise_distances(
        metric, Xs,
        verbose=False, enable_caching=True
    )

    # Compute pairwise distances without caching.
    D2 = pairwise_distances(
        metric, Xs,
        verbose=False, enable_caching=False
    )
    assert np.max(np.abs(D1 - D2)) < TOL


@pytest.mark.parametrize('seed', [1, 2, 3])
@pytest.mark.parametrize('group', ['orth', 'perm'])
@pytest.mark.parametrize('method', ['full_batch', 'streaming'])
@pytest.mark.parametrize('m', [100])
@pytest.mark.parametrize('n', [10])
@pytest.mark.parametrize('num_X', [4])
def test_frechet_mean(seed, group, method, m, n, num_X):

    # Set random seed, draw random rotation.
    rs = check_random_state(seed)
    _Xb = rs.randn(m, n)
    Xs = [_Xb for _ in range(num_X)]

    Xbar, aligned_Xs = frechet_mean(
        Xs, group=group, return_aligned_Xs=True, method=method
    )

    assert np.all(
        pdist(np.stack(aligned_Xs).reshape(num_X, -1)) < TOL
    )
