"""
Core functions for manipulating quantum objects.
"""

import numpy as np
import scipy.sparse as sp
from numexpr import evaluate as evl
from numba import jit


def qonvert(data, qtype=None, sparse=False, nrmlz=False):
    """ Converts lists to 'quantum' i.e. complex matrices, kets being columns.
    Input:
        data:  list describing entries
        qtype: output type, either 'ket', 'bra' or 'dop' if given
        sparse: convert output to sparse 'csr' format.
    Returns:
        x: numpy or sparse matrix
    * Will unravel an array if 'ket' or 'bra' given.
    * Will conjugate if 'bra' given.
    * Will leave operators as is if 'dop' given, but construct one
    them if vector given.
    TODO: convert sparse vector to sparse operator
    """
    p = np.matrix(data, copy=False, dtype=complex)
    if qtype is not None:
        sz = np.prod(p.shape)
        if qtype in ('k', 'ket'):
            p.shape = (sz, 1)
        elif qtype in ('b', 'bra'):
            p.shape = (1, sz)
            p = np.conj(p)
        elif qtype in ('p', 'd', 'r', 'rho', 'op', 'dop') and not isop(p):
            p = qonvert(p, 'k') * qonvert(p, 'k').H
    if nrmlz:
        p = nrmlz(p)
    return sp.csr_matrix(p, dtype=complex) if sparse else p


@jit
def isket(p):
    """ Checks if matrix is in ket form, i.e. a column """
    return p.shape[0] > 1 and p.shape[1] == 1  # Column vector check


@jit
def isbra(p):
    """ Checks if matrix is in bra form, i.e. a row """
    return p.shape[0] == 1 and p.shape[1] > 1  # Row vector check


@jit
def isop(p):
    """ Checks if matrix is an operator, i.e. square """
    m, n = p.shape
    return m == n and m > 1  # Square matrix check


def isherm(a):
    """ Checks if matrix is hermitian, for sparse or dense"""
    if sp.issparse(a):
        # Since sparse, test that no .H elements are not unequal..
        return (a != a.H).nnz == 0
    return np.allclose(a, a.H)


@jit
def tr(a):
    """ Trace of hermitian matrix (jit version faster than numpy!)
    TODO: sparse method
    """
    x = 0.0
    for i in range(a.shape[0]):
        x += a[i, i].real
    return x


def nrmlz(p):
    """ Returns the state p in normalized form """
    return (p / (p.H * p)[0, 0]**0.5 if isket(p) else
            p / (p * p.H)[0, 0]**0.5 if isbra(p) else
            p / tr(p))


@jit
def krnd2(a, b):
    """
    Fast tensor product of two dense arrays (Fast than numpy using jit)
    """
    m, n = a.shape
    p, q = b.shape
    x = np.empty((m * p, n * q), dtype=complex)
    for i in range(m):
        for j in range(n):
            x[i * p:(i + 1)*p, j * q:(j + 1) * q] = a[i, j] * b
    return np.asmatrix(x)
# def krnd2(a, b):  # Fallback for debugging
#     return kron(a, b)


def kron(*ps):
    """ Tensor product of variable number of arguments.
    Input:
        ps: objects to be tensored together
    Returns:
        operator
    The product is performed as (a * (b * (c * ...)))
    """
    pn = len(ps)
    a = ps[0]
    if pn == 1:
        return a
    b = ps[1] if pn == 2 else  \
        kron(*ps[1:])  # Recursively perform kron to 'right'
    return (sp.kron(a, b, 'csr') if (sp.issparse(a) or sp.issparse(b)) else
            krnd2(a, b))


def kronpow(a, pwr):
    """ Returns 'a' tensored with itself pwr times """
    return (1 if pwr == 0 else
            a if pwr == 1 else
            kron(*[a] * pwr))


def eye(n, sparse=False):
    """ Return identity of size n in complex format, optionally sparse"""
    return (sp.eye(n, dtype=complex, format='csr') if sparse else
            np.eye(n, dtype=complex))


def eyepad(a, dims, inds, sparse=None):
    """ Pad an operator with identities to act on particular subsystem.
    Input:
        a: operator to act
        dims: list of dimensions of subsystems.
        inds: indices of dims to act a on.
        sparse: whether output should be sparse
    Returns:
        b: operator with a acting on each subsystem specified by inds
    Note that the actual numbers in dims[inds] are ignored and the size of
    a is assumed to match. Sparsity of the output can be inferred from
    input if not specified.
    e.g.
    >>> X = sig('x')
    >>> b1 = kron(X, eye(2), X, eye(2))
    >>> b2 = eyepad(X, dims=[2]*4, inds=[0,2])
    >>> allclose(b1, b2)
    True
    """
    sparse = sp.issparse(a) if sparse is None else sparse  # infer sparsity
    inds = np.array(inds, ndmin=1)
    b = eye(np.prod(dims[0:inds[0]]), sparse=sparse)
    for i in range(len(inds) - 1):
        b = kron(b, a)
        pad_size = np.prod(dims[inds[i] + 1:inds[i + 1]])
        b = kron(b, eye(pad_size, sparse=sparse))
    b = kron(b, a)
    pad_size = np.prod(dims[inds[-1] + 1:])
    b = kron(b, eye(pad_size, sparse=sparse))
    return b


def chop(x, tol=1.0e-14):
    """
    Sets any values of x smaller than tol (relative to range(x)) to zero.
    Acts in-place on array!
    """
    rnge = abs(x.max() - x.min())
    minm = rnge * tol  # minimum value tolerated
    if sp.issparse(x):
        x.data.real[np.abs(x.data.real) < minm] = 0.0
        x.data.imag[np.abs(x.data.imag) < minm] = 0.0
        x.eliminate_zeros()
    else:
        x.real[np.abs(x.real) < minm] = 0.0
        x.imag[np.abs(x.imag) < minm] = 0.0
    return x


def ldmul(v, m):
    '''
    Fast left diagonal multiplication using numexpr
    Args:
        v: vector of diagonal matrix, can be array
        m: matrix
    '''
    v = v.reshape(np.size(v), 1)
    return evl('v*m')


def rdmul(m, v):
    '''
    Fast right diagonal multiplication using numexpr
    Args:
        m: matrix
        v: vector of diagonal matrix, can be array
    '''
    v = v.reshape(1, np.size(v))
    return evl('m*v')


def comm(a, b):
    """ Commutator of two matrices """
    return a * b - b * a


def infer_num_qubits(p):
    """ Infers the size of a state assumed to be made of qubits """
    d = max(p.shape)
    return int(np.log2(d))