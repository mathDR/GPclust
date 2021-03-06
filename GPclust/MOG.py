# Copyright (c) 2012, 2013, 2014 James Hensman
# Licensed under the GPL v3 (see LICENSE.txt)

import numpy as np
import gpflow
import tensorflow as tf
from .collapsed_mixture import CollapsedMixture

from .tf_utilities import lngammad, tensor_lngammad
from gpflow._settings import settings
float_type = settings.dtypes.float_type

class MOG(CollapsedMixture):
    """
    A Mixture of Gaussians, using the fast variational framework

    Arguments
    =========
    X - a np.array of the observed data: each row contains one datum.
    num_clusters - the number of clusters (or initial number of clusters in the Dirichlet Process case)
    alpha - the A priori dirichlet concentrationn parameter (default 1.)
    prior_Z  - either 'symmetric' or 'DP', specifies whether to use a symmetric
               Dirichlet prior for the clusters, or a (truncated) Dirichlet process.
    name - a convenient string for printing the model (default MOG)

    Optional arguments for the parameters of the Gaussian-Wishart priors on the clusters
    prior_m - prior mean (defaults to mean of the data)
    prior_kappa - prior connectivity (default 1e-6)
    prior_S - prior Wishart covariance (defaults to 1e-3 * I)
    prior_v - prior Wishart degrees of freedom (defaults to dimension of the problem +1.)

    """
    def __init__(self, X, num_clusters=2, prior_Z='symmetric', alpha=1.,
                 prior_m=None, prior_kappa=1e-6, prior_S=None, prior_v=None):
        self.num_data, self.D = X.shape
        self.X = gpflow.param.DataHolder(X, on_shape_change='pass')
        self.LOGPI = np.log(np.pi)

        # store the prior cluster parameters
        self.m0 = X.mean(0) if prior_m is None else prior_m
        self.k0 = prior_kappa
        self.S0 = np.eye(self.D)*1.e-3 if prior_S is None else prior_S
        self.v0 = prior_v or np.array(self.D + 1.)

        # precomputed stuff
        self.k0m0m0T = gpflow.param.DataHolder(self.k0*self.m0[:, np.newaxis]*self.m0[np.newaxis, :])
        XXT = X[:, :, np.newaxis]*X[:, np.newaxis, :]
        self.XXT = XXT
        self.S0_halflogdet = np.sum(np.log(np.sqrt(np.diag(np.linalg.cholesky(self.S0)))))

        CollapsedMixture.__init__(self, self.num_data, num_clusters, prior_Z, alpha)

    def get_components(self):
        # Generate the shared elements both build_likelihood and predict_components_tf need.
        # Note, only Sns_chol is returned since predict_components_tf need the inverses
        phi = tf.nn.softmax(self.logphi)
        phi_hat = tf.reduce_sum(phi, 0)

        # computations needed for bound, gradient and predictions
        kNs = phi_hat + self.k0
        vNs = phi_hat + self.v0
        Xsumk = tf.matmul(tf.transpose(phi), self.X)  # K x D
        Ck = tf.reduce_sum(tf.expand_dims(tf.expand_dims(tf.transpose(phi), 2), 2)
                           * tf.expand_dims(self.XXT, 0), 1)  # K x D x D
        mun = (self.k0 * tf.reshape(self.m0, [1, -1]) + Xsumk) / tf.reshape(kNs, [-1, 1])  # K x D
        munmunT = tf.expand_dims(mun, 1) * tf.expand_dims(mun, 2)  # K x D x D
        Sns = tf.expand_dims(self.S0 + self.k0m0m0T, 0) + Ck - tf.reshape(kNs, [-1, 1, 1]) * munmunT
        Sns_chol = tf.cholesky(Sns)
        return kNs, vNs, mun, Sns_chol

    def build_likelihood(self):
        kNs, vNs, _, Sns_chol = self.get_components()

        Sns_logdet = 2 * tf.reduce_sum(tf.log(tf.matrix_diag_part(Sns_chol)), 1)

        return -0.5*self.D*tf.reduce_sum(tf.log(kNs/self.k0))\
            + self.num_clusters*self.v0*self.S0_halflogdet - 0.5 * tf.reduce_sum(vNs * Sns_logdet)\
            + tf.reduce_sum(tensor_lngammad(vNs, self.D)) - self.num_clusters * lngammad(self.v0, self.D)\
            - self.build_KL_Z()\
            - 0.5*self.num_data*self.D*self.LOGPI

    def predict_components_tf(self, Xnew):
        """
        The tensorflow graph for the predictive density under each component at Xnew
        """
        kNs, vNs, mun, Sns_chol = self.get_components()

        RHS = tf.reshape(tf.tile(tf.eye(self.D,dtype=float_type),tf.stack([tf.shape(Sns_chol)[0],1])),\
            tf.stack([tf.shape(Sns_chol)[0],self.D,self.D]))
        Sns_invs = tf.cholesky_solve(Sns_chol,RHS) # Is there a better way to do this?
        Sns_logdet = 2 * tf.reduce_sum(tf.log(tf.matrix_diag_part(Sns_chol)), 1)


        Dist = tf.expand_dims(Xnew, 1) - tf.expand_dims(mun, 0)  # Nnew x K x D
        h = tf.tile(tf.expand_dims(Sns_invs, 0), tf.stack([tf.shape(Dist)[0], 1, 1, 1]))
        tmp = tf.reduce_sum(tf.multiply(tf.expand_dims(Dist, 3), h), 2) # N x K x D
        mahalanobis = tf.reduce_sum(tf.multiply(tmp, Dist), 2)/(kNs+1.)*kNs*(vNs-self.D+1.) # N x K
        halflndetSigma = 0.5*(Sns_logdet + self.D*tf.log((kNs+1.)/(kNs*(vNs-self.D+1.))))
        Z = tf.lgamma(0.5*(tf.expand_dims(vNs, 0)+1.))-tf.lgamma(0.5*(tf.expand_dims(vNs, 0)-self.D+1.))\
            - (0.5*self.D)*(tf.log(tf.expand_dims(vNs, 0)-self.D+1.) + self.LOGPI)\
            - halflndetSigma\
            - (0.5*(tf.expand_dims(vNs, 0)+1.))*tf.log(1.+mahalanobis/(tf.expand_dims(vNs, 0)-self.D+1.))

        return tf.exp(Z)


    @gpflow.param.AutoFlow((tf.float64, [None, None]))
    def predict_components(self, Xnew):
        """
        The tensorflow graph for the predictive density under each component at Xnew
        """
        return self.predict_components_tf(Xnew)

    @gpflow.param.AutoFlow((tf.float64, [None, None]))
    def predict(self, Xnew):
        """The predictive density of the model at Xnew"""
        Z = self.predict_components_tf(Xnew)
        # calculate the weights for each component
        phi = tf.nn.softmax(self.logphi)
        phi_hat = tf.reduce_sum(phi, 0)
        pie = tf.add(phi_hat, self.alpha)
        pie = tf.div(pie, tf.reduce_sum(pie))
        return tf.reduce_sum(tf.multiply(Z, tf.expand_dims(pie, 0)), 1)

    #@gpflow.param.AutoFlow((tf.float64), (tf.float64))
    @gpflow.param.AutoFlow()
    def get_means_and_covariances(self):
        # Generate the shared elements both build_likelihood and predict_components_tf need.
        # Note, only Sns_chol is returned since predict_components_tf need the inverses
        phi = tf.nn.softmax(self.logphi)
        phi_hat = tf.reduce_sum(phi, 0)

        # computations needed for bound, gradient and predictions
        kNs = phi_hat + self.k0
        Xsumk = tf.matmul(tf.transpose(phi), self.X)  # K x D
        Ck = tf.reduce_sum(tf.expand_dims(tf.expand_dims(tf.transpose(phi), 2), 2)
                           * tf.expand_dims(self.XXT, 0), 1)  # K x D x D
        mun = (self.k0 * tf.reshape(self.m0, [1, -1]) + Xsumk) / tf.reshape(kNs, [-1, 1])  # K x D
        munmunT = tf.expand_dims(mun, 1) * tf.expand_dims(mun, 2)  # K x D x D
        Sns = tf.expand_dims(self.S0 + self.k0m0m0T, 0) + Ck - tf.reshape(kNs, [-1, 1, 1]) * munmunT
        return mun, Sns
