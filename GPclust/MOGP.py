# Copyright (c) 2012, 2013, 2014 James Hensman
# Licensed under the GPL v3 (see LICENSE.txt)

import numpy as np
from .collapsed_mixture import CollapsedMixture
import gpflow
import tensorflow as tf
from gpflow._settings import settings
float_type = settings.dtypes.float_type

class MOGP(CollapsedMixture):
    """
    A Generalized Mixture of Gaussian Processes

    Arguments
    =========
    X        - The times of observation of the time series in a *list* of np.arrays. Each
               entry in the list is a T_n x 1 array.
    Y        - the observed values at the times corresponding to X. A list of np.arrays.
    Z        - inducing point positions (M x 1 numpy array)
    kernF    - A gpflow kernel to model the function associated with each cluster.
    likelihood  - A gpflow Clikelihood object to represnt (potentially non-gaussian) obsevation distributions.
    alpha    - The a priori Dirichlet concentrationn parameter (default 1.)
    prior_Z  - Either 'symmetric' or 'dp', specifies whether to use a symmetric Dirichlet
               prior for the clusters, or a (truncated) Dirichlet Process.
    name     - A convenient string for printing the model (default MOHGP)

    """
    def __init__(self, X, Y, Z=None, kernF=None, likelihood=None, num_clusters=2, alpha=1., prior_Z='symmetric'):

        assert len(X) == len(Y)
        for x, y in zip(X, Y):
            assert x.shape == y.shape
        num_data = len(X)
        self.X, self.Y = X, Y

        CollapsedMixture.__init__(self, num_data, num_clusters, prior_Z, alpha)

        self.kern = kernF
        self.likelihood = likelihood
        if Z is None:
            # Choose 10 inducing points across the range of X
            Z = np.linspace(np.min(X),np.max(X),10)

        self.Z = Z

        #initialize variational parameters
        M = Z.shape[0]
        self.q_mu = gpflow.param.Param(np.random.randn(M, num_clusters))
        q_sqrt = np.array([np.eye(M) for _ in range(num_clusters)]).swapaxes(0, 2)
        self.q_sqrt = gpflow.param.Param(q_sqrt)


        self.LOG2PI = np.log(2.*np.pi)

    def build_likelihood(self):
        loglik = 0.
        phi = tf.nn.softmax(self.logphi)
        for i, (Xi, Yi) in enumerate(zip(self.X, self.Y)):
            # get mean and variance of each GP at the observed points. the
            # different mean and variances for the clusters are stored in the
            # columns.
            mu, var = gpflow.conditionals.conditional(Xi, self.Z, self.kern, self.q_mu,
                                               q_sqrt=self.q_sqrt, full_cov=False, whiten=False)

            # duplicate columns of Y so that we can compute likelihoods for all clusters in one go.
            Ystacked = tf.tile(Yi, [1, self.num_clusters])

            # Get variational expectations.
            var_exp = self.likelihood.variational_expectations(mu, var, Ystacked)
            phi_i = phi[i]
            loglik += tf.reduce_sum(phi_i * tf.reduce_sum(var_exp, 0))

        KL_u = gpflow.kullback_leiblers.gauss_kl(self.q_mu, self.q_sqrt, self.kern.K(self.Z))
        return loglik - KL_u - self.build_KL_Z()

    @gpflow.param.AutoFlow((tf.float64, [None, None]))
    def predict_f(self, Xnew):
        return gpflow.conditionals.conditional(Xi, self.Z, self.kern, self.q_mu,
                                        q_sqrt=self.q_sqrt, full_cov=False, whiten=False)

    @gpflow.param.AutoFlow((tf.float64, [None, None]))
    def predict_y(self, Xnew):
        mu, var = gpflow.conditionals.conditional(Xi, self.Z, self.kern, self.q_mu,
                                           q_sqrt=self.q_sqrt, full_cov=False, whiten=False)
        return self.likelihood.predict_mean_and_var(mu, var)


    @gpflow.param.AutoFlow((tf.float64, [None, None]))
    def predict_components(self, Xnew):
        return mu, var
