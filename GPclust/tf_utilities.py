import numpy as np
import tensorflow as tf
import GPy
import GPflow

def tf_multiple_pdinv(A):
    """
    Arguments
    ---------
    A : A DxDxN numpy array (each A[:,:,i] is pd)

    Returns
    -------
    invs : the inverses of A
    hld: 0.5* the log of the determinants of A
    """
    A = tf.convert_to_tensor(A)
    D1, D, N = A.get_shape()
    chols = tf.batch_cholesky(tf.reshape(tf.transpose(tf.reshape(A,tf.pack([D*D,N])) +\
        tf.reshape(1e-6*GPflow.tf_hacks.eye(D),tf.pack([D*D,1]))),tf.pack([N,D,D])))
    print chols.get_shape()
    print GPflow.tf_hacks.eye(D).get_shape()

    invs = tf.batch_matrix_triangular_solve(chols, tf.expand_dims(GPflow.tf_hacks.eye(D),0), lower=True)
    halflogdets = tf.reduce_sum(tf.log(tf.batch_matrix_diag_part(chols)),1)
    #invs = [GPy.util.linalg.dpotri(L,True)[0] for L in chols]
    #invs = [np.triu(I)+np.triu(I,1).T for I in invs]
    #invs = tf.batch_matrix_band_part(invs,0,-1) +\
    #    tf.batch_matrix_transpose(tf.batch_matrix_band_part(invs,0,-1)-tf.batch_matrix_band_part(invs,0,0))
    return invs, halflogdets

def multiple_pdinv(A):
    N = A.shape[-1]
    chols = [GPy.util.linalg.jitchol(A[:,:,i]) for i in range(N)]
    halflogdets = [np.sum(np.log(np.diag(L))) for L in chols]
    invs = [GPy.util.linalg.dpotri(L,True)[0] for L in chols]
    invs = [np.triu(I)+np.triu(I,1).T for I in invs]
    return np.dstack(invs),np.array(halflogdets)

def lngammad(v, D):
    lgd = tf.reduce_sum(tf.lgamma(0.5*(v + 1.0 - tf.linspace(1., tf.cast(D, tf.float32), D))))
    return lgd


def softmax(X):
    phi = tf.nn.softmax(X, name='phi')
    log_phi = tf.nn.log_softmax(X, name='log_phi')
    H = -tf.reduce_sum(tf.mul(phi, log_phi), name='H')
    return phi, log_phi, H


def ln_dirichlet_C(a):
    return tf.lgamma(tf.reduce_sum(a)) - tf.reduce_sum(tf.lgamma(a))

if __name__ == '__main__':
    A = np.random.rand(3,3,4)
    A = (A.reshape(3*3,4) + np.eye(3).reshape(3*3,1)).reshape(3,3,4)
    invs, halflogdets = multiple_pdinv(A)
    #print invs
    print 'halflogdets = ',halflogdets
    tfinvs, tfhalflogdets = tf_multiple_pdinv(A)
    with tf.Session() as sess:
        res = sess.run([tfinvs,tfhalflogdets])
        print res[1]

    '''
    # lngammad
    v = 5.1
    D = 5
    lgd = lngammad(v, D)
    with tf.Session() as sess:
        res = sess.run(lgd)
        assert np.isclose(res, 0.67775756)

    X = np.random.randn(5, 3)
    phi, log_phi, H = softmax(X)
    with tf.Session() as sess:
        res = sess.run([phi, log_phi, H])
        print(res)

    a = 2.0*np.ones(5)
    ldc = ln_dirichlet_C(a)
    with tf.Session() as sess:
        res = sess.run(ldc)
        print(res)
    '''
