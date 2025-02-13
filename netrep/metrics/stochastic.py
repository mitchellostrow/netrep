from __future__ import annotations
import itertools
from typing import Tuple, Optional, Union, Literal, List

import numpy as np
import numpy.typing as npt
from sklearn.utils.validation import check_random_state

from netrep.utils import align, sq_bures_metric, rand_orth


class GaussianStochasticMetric:
    """2-Wasserstein distance between Gaussian-distributed network responses.

    Attributes
    ----------
    alpha: float between 0 and 2
        Interpolates between covariance-only and mean-only distance metrics.
        When alpha == 0: only uses covariance.
        When alpha == 1: computes 2-Wasserstein.
        When alpha == 2: only uses means (i.e. deterministic metric).
    group: Literal["orth", "perm", "identity"]
        Invariance group over which to optimize.
    init: Literal["means", "rand"]
        Transform initialization.
    niter: int
        Number of optimization iterations.
    tol: float
        Optimization tolerance.
    n_restarts: int
        Number of restarts. Only valid when `init` is "rand".
    T: np.ndarray
        Optimal alignment matrix.
    loss_hist: List[float]
        Loss history.
    """

    def __init__(
            self, 
            alpha: float=1.0, 
            group: Literal["orth", "perm", "identity"] = "orth", 
            init: Literal["means", "rand"] = "means", 
            niter: int = 1000, 
            tol: float = 1e-8,
            random_state: Optional[Union[int, np.random.RandomState]]=None, 
            n_restarts: int = 1,
    ):
        if (alpha < 0) or (alpha > 2):
            raise ValueError("alpha parameter should be between zero and two.")
        self.alpha = alpha
        self.group = group
        self.init = init
        self.niter = niter
        self.tol = tol
        self._rs = check_random_state(random_state)
        self.n_restarts = n_restarts
        if self.init == "means":
            assert n_restarts == 1

    def fit(
        self, 
        X: Tuple[npt.NDArray, npt.NDArray], 
        Y: Tuple[npt.NDArray, npt.NDArray]
    ) -> GaussianStochasticMetric:
        """Aligns network responses with interpolated 2-Wasserstein ground metric.

        Parameters
        ----------
        X : Tuple[np.ndarray, np.ndarray]
            Tuple of (means, covariances) for first set of network responses. Means has
            shape (n_images, n_neurons) and covariances has shape 
            (n_images, n_neurons, n_neurons).
        Y : Tuple[np.ndarray, np.ndarray]
            Tuple of (means, covariances) for second set of network responses. Means has
            shape (n_images, n_neurons) and covariances has shape   
            (n_images, n_neurons, n_neurons).
        
        Returns
        -------
        self: GaussianStochasticMetric
            Instance of class with optimal alignment matrix stored in `self.T`.
        """
        means_X, covs_X = X
        means_Y, covs_Y = Y

        assert means_X.shape == means_Y.shape
        assert covs_X.shape == covs_Y.shape
        assert means_X.shape[0] == covs_X.shape[0]
        assert means_X.shape[1] == covs_X.shape[1]
        assert means_X.shape[1] == covs_X.shape[2]

        best_loss = np.inf
        for _ in range(self.n_restarts):

            if self.init == "means":
                init_T = align(means_Y, means_X, group=self.group)
            elif self.init == "rand":
                init_T = rand_orth(means_X.shape[1], random_state=self._rs)

            T, loss_hist = _fit_gaussian_alignment(
                means_X, means_Y, covs_X, covs_Y, init_T,
                self.alpha, self.group, self.niter, self.tol
            )
            if best_loss > loss_hist[-1]:
                best_loss = loss_hist[-1]
                best_T = T

        self.T = best_T
        self.loss_hist = loss_hist
        return self

    def transform(
        self, 
        X: Tuple[npt.NDArray, npt.NDArray], 
        Y: Tuple[npt.NDArray, npt.NDArray]
    ) -> Tuple[Tuple[npt.NDArray, npt.NDArray], Tuple[npt.NDArray, npt.NDArray]]:
        """Aligns second set of network responses with first set.

        Parameters
        ----------
        X : Tuple[np.ndarray, np.ndarray]
            Tuple of (means, covariances) for first set of network responses. Means has
            shape (n_images, n_neurons) and covariances has shape 
            (n_images, n_neurons, n_neurons).
        Y : Tuple[np.ndarray, np.ndarray]
            Tuple of (means, covariances) for second set of network responses. Means has
            shape (n_images, n_neurons) and covariances has shape
            (n_images, n_neurons, n_neurons).

        Returns
        -------
        X : Tuple[np.ndarray, np.ndarray]
            Same as input.
        Y_transformed : Tuple[np.ndarray, np.ndarray]
            Aligned tuple of (means, covariances) for second set of network responses.
        """
        means_Y, covs_Y = Y
        Y_transformed = (
            means_Y @ self.T,
            np.einsum("ijk,jl,kp->ilp", covs_Y, self.T, self.T)
        )
        return X, Y_transformed

    def score(
        self, 
        X: Tuple[npt.NDArray, npt.NDArray], 
        Y: Tuple[npt.NDArray, npt.NDArray]
    ) -> float:
        """Computes interpolated 2-Wasserstein distance between aligned network responses.

        Parameters
        ----------
        X: Tuple[np.ndarray, np.ndarray]
            Tuple of (means, covariances) for first set of network responses. Means has
            shape (n_images, n_neurons) and covariances has shape
            (n_images, n_neurons, n_neurons).
        Y: Tuple[np.ndarray, np.ndarray]
            Tuple of (means, covariances) for second set of network responses. Means has
            shape (n_images, n_neurons) and covariances has shape
            (n_images, n_neurons, n_neurons).

        Returns
        -------        
        score: float
            Interpolated 2-Wasserstein distance between aligned network responses.
        """
        X, Y = self.transform(X, Y)
        mX, sX = X
        mY, sY = Y

        A = np.sum((mX - mY) ** 2, axis=1)
        B = np.array([sq_bures_metric(sx, sy) for sx, sy in zip(sX, sY)])
        mn = np.mean(self.alpha * A + (2 - self.alpha) * B)
        # mn should always be positive but sometimes numerical rounding errors
        # cause mn to be very slightly negative, causing sqrt(mn) to be nan.
        # Thus, we take sqrt(abs(mn)) and pass through the sign. Any large
        # negative outputs should be caught by unit tests.
        return np.sign(mn) * np.sqrt(abs(mn))

    def fit_score(
        self, 
        X: Tuple[npt.NDArray, npt.NDArray], 
        Y: Tuple[npt.NDArray, npt.NDArray]
        ) -> float:
        """Fits alignment matrix and returns distance.

        Parameters
        ----------
        X: Tuple[np.ndarray, np.ndarray]
            Tuple of (means, covariances) for first set of network responses. Means has
            shape (n_images, n_neurons) and covariances has shape
            (n_images, n_neurons, n_neurons).
        Y: Tuple[np.ndarray, np.ndarray]
            Tuple of (means, covariances) for second set of network responses. Means has
            shape (n_images, n_neurons) and covariances has shape
            (n_images, n_neurons, n_neurons).
        
        Returns
        -------
        score: float
            Interpolated 2-Wasserstein distance between aligned network responses.
        """
        return self.fit(X, Y).score(X, Y)


class EnergyStochasticMetric:
    """Optimal alignment of network responses using energy distance as the ground metric.

    Attributes
    ----------
    group: Literal["orth", "perm", "identity"]
        Invariance group over which to optimize.
    niter: int
        Number of optimization iterations. 
    tol: float
        Defaults to 1e-6.
    Q: np.ndarray
        Optimal alignment matrix.
    loss_hist: List[float]
    """

    def __init__(
        self, 
        group: Literal["orth", "perm", "identity"] = "orth", 
        niter: int = 100, 
        tol: float = 1e-6):

        self.group = group
        self.niter = niter
        self.tol = tol

    def fit(
        self, 
        X: npt.NDArray, 
        Y: npt.NDArray
    ) -> EnergyStochasticMetric:
        """Fits optimal matrix that aligns network responses Y to X.

        Parameters
        ----------
        X : np.ndarray
            Responses of first network with Size[(images, repeats, neurons]).
        Y : np.ndarray
            Responses of second network with Size[(images, repeats, neurons]).

        Returns
        -------
        self : EnergyStochasticMetric
            Class instance with updated state.
        """
        assert X.shape == Y.shape

        r = X.shape[1]

        idx = np.array(list(itertools.product(range(r), range(r))))
        X = np.row_stack([x[idx[:, 0]] for x in X])
        Y = np.row_stack([y[idx[:, 1]] for y in Y])

        w = np.ones(X.shape[0])
        loss_hist = [np.mean(np.linalg.norm(X - Y, axis=-1))]

        for _ in range(self.niter):
            Q = align(w[:, None] * Y, w[:, None] * X, group=self.group)
            resid = np.linalg.norm(X - Y @ Q, axis=-1)
            loss_hist.append(np.mean(resid))
            w = 1 / np.maximum(np.sqrt(resid), 1e-6)
            if (loss_hist[-2] - loss_hist[-1]) < self.tol:
                break

        self.w = w
        self.Q = Q
        self.loss_hist = loss_hist
        return self

    def transform(
        self, 
        X: npt.NDArray, 
        Y: npt.NDArray
    ) -> Tuple[npt.NDArray, npt.NDArray]:
        """Aligns second network responses to first network responses.

        Parameters
        ----------
        X : np.ndarray
            First network's responses, with Size[(images, repeats, neurons)].
        Y : np.ndarray
            Second network's responses, with Size[(images, repeats, neurons)].

        Returns
        -------
        X : np.ndarray
            First network's responses, with Size[(images, repeats, neurons)].
        Y_aligned : np.ndarray
            Aligned second network's responses, with Size[(images, repeats, neurons)].
        """
        assert X.shape == Y.shape
        Y_aligned = np.einsum("ijk,kl->ijl", Y, self.Q)
        return X, Y_aligned

    def score(self, X: npt.NDArray, Y: npt.NDArray) -> float:
        """Compute the Energy distance metric between two networks.

        Parameters
        ----------
        X : np.ndarray
            First network's responses, with Size[(images, repeats, neurons)].
        Y : np.ndarray
            Second network's responses, with Size[(images, repeats, neurons)].
        
        Returns
        -------
        score : float
            Energy distance metric between two networks.
        """
        X, Y = self.transform(X, Y)
        m = X.shape[0] # num images
        n_samples = X.shape[1]

        combs = np.array(list(
            itertools.combinations(range(n_samples), 2)
        ))
        prod = np.array(list(
            itertools.product(range(n_samples), range(n_samples))
        ))
        
        d_xy, d_xx, d_yy = 0, 0, 0
        for i in range(m):
            d_xy += np.mean(np.linalg.norm(X[i][prod[:, 0]] - Y[i][prod[:, 1]], axis=-1))
            d_xx += np.mean(np.linalg.norm(X[i][combs[:, 0]] - X[i][combs[:, 1]], axis=-1))
            d_yy += np.mean(np.linalg.norm(Y[i][combs[:, 0]] - Y[i][combs[:, 1]], axis=-1))

        return np.sqrt(max(0, (d_xy / m) - .5*((d_xx / m) + (d_yy / m))))

    def fit_score(self, X: npt.NDArray, Y: npt.NDArray) -> float:
        """Fits optimal alignment and computes the Energy distance metric between two networks.

        Parameters
        ----------
        X : np.ndarray
            First network's responses, with Size[(images, repeats, neurons)].
        Y : np.ndarray
            Second network's responses, with Size[(images, repeats, neurons)].
        
        Returns
        -------
        score : float
            Energy distance metric between two networks.
        """
        return self.fit(X, Y).score(X, Y)


def _fit_gaussian_alignment(
        means_X: npt.NDArray, 
        means_Y: npt.NDArray, 
        covs_X: npt.NDArray, 
        covs_Y: npt.NDArray, 
        T: npt.NDArray, 
        alpha: float, 
        group: Literal["orth", "perm", "identity"], 
        niter: int, 
        tol: float,
    ) -> Tuple[npt.NDArray, List[float]]:
    """Helper function for fitting alignment between Gaussian-distributed responses."""

    vX, uX = np.linalg.eigh(covs_X)
    sX = np.einsum("ijk,ik,ilk->ijl", uX, np.sqrt(vX), uX)
    
    vY, uY = np.linalg.eigh(covs_Y)
    sY = np.einsum("ijk,ik,ilk->ijl", uY, np.sqrt(vY), uY)

    loss_hist = []

    for i in range(niter):
        Qs = [align(T.T @ sy, sx, group="orth") for sx, sy in zip(sX, sY)]
        A = np.row_stack(
            [alpha * means_X] +
            [(2 - alpha) * sx for sx in sX]
        )
        r_sY = []
        B = np.row_stack(
            [alpha * means_Y] +
            [Q.T @ ((2 - alpha) * sy) for Q, sy in zip(Qs, sY)]
        )
        T = align(B, A, group=group)
        loss_hist.append(np.linalg.norm(A - B @ T))
        if i < 2:
            pass
        elif (loss_hist[-2] - loss_hist[-1]) < tol:
            break

    return T, loss_hist
