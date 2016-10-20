# Bojan Nikolic <b.nikolic@mrao.cam.ac.uk>
#
# Synthesise and Image interferometer data
"""Convolutional gridding support functions

Parameter name meanings:

- p: The uvw coordinates [*,3] (m)
- v: The Visibility values [*] (Jy)
- field_of_view: Width of the field of view to be synthesised, as directional
  cosines (approximately radians)
- lam: Width of the uv-plane (in wavelengths). Controls resolution of the
  images.
- kernel_oversampling: Oversampling of pixels by the convolution kernels -- there are
  (kernel_oversampling x kernel_oversampling) convolution kernels per pixels to account for fractional
  pixel values.

All grids and images are considered quadratic and centered around
`npixel//2`, where `npixel` is the pixel width/height. This means that `npixel//2` is
the zero frequency for FFT purposes, as is convention. Note that this
means that for even `npixel` the grid is not symetrical, which means that
e.g. for convolution kernels odd image sizes are preferred.

This is implemented for reference in
`coordinates`/`coordinates2`. Some noteworthy properties:
- `ceil(field_of_view * lam)` gives the image size `npixel` in pixels
- `lam * coordinates2(npixel)` yields the `u,v` grid coordinate system
- `field_of_view * coordinates2(npixel)` yields the `l,m` image coordinate system
   (radians, roughly)
   
"""

from __future__ import division

import scipy.special

from arl.fft_support import *


def _coordinateBounds(npixel):
    r""" Returns lowest and highest coordinates of an image/grid given:

    1. Step size is :math:`1/npixel`:

       .. math:: \frac{high-low}{npixel-1} = \frac{1}{npixel}

    2. The coordinate :math:`\lfloor npixel/2\rfloor` falls exactly on zero:

       .. math:: low + \left\lfloor\frac{npixel}{2}\right\rfloor * (high-low) = 0

    This is the coordinate system for shifted FFTs.
    """
    if npixel % 2 == 0:
        return -0.5, 0.5 * (npixel - 2) / npixel
    else:
        return -0.5 * (npixel - 1) / npixel, 0.5 * (npixel - 1) / npixel


def _coordinates(npixel):
    """ 1D array which spans [-.5,.5[ with 0 at position npixel/2
    
    """
    low, high = _coordinateBounds(npixel)
    return numpy.mgrid[low:high:(npixel * 1j)]


def _coordinates2(npixel):
    """Two dimensional grids of coordinates spanning -1 to 1 in each dimension

    1. a step size of 2/npixel and
    2. (0,0) at pixel (floor(n/2),floor(n/2))
    """
    low, high = _coordinateBounds(npixel)
    return numpy.mgrid[low:high:(npixel * 1j), low:high:(npixel * 1j)]


def anti_aliasing_function(shape, m, c):
    """
    Compute the prolate spheroidal anti-aliasing function

    See VLA Scientific Memoranda 129, 131, 132
    :param shape: (height, width) pair
    :param m: mode parameter
    :param c: spheroidal parameter
    """
    
    # 2D Prolate spheroidal angular function is separable
    sy, sx = [scipy.special.pro_ang1(m, m, c, _coordinates(npixel))[0] for npixel in shape]
    return numpy.outer(sy, sx)


def _w_kernel_function(npixel, field_of_view, w):
    """
    W beam, the fresnel diffraction pattern arising from non-coplanar baselines

    :param npixel: Size of the grid in pixels
    :param field_of_view: Field of view
    :param w: Baseline distance to the projection plane
    :returns: npixel x npixel array with the far field
    """
    
    m, l = _coordinates2(npixel) * field_of_view
    r2 = l ** 2 + m ** 2
    assert numpy.array(r2 < 1.0).all(), \
        "Error in image coordinate system: field_of_view %f, npixel %f,l %s, m %s" % (field_of_view, npixel, l, m)
    ph = w * (1 - numpy.sqrt(1.0 - r2))
    cp = numpy.exp(2j * numpy.pi * ph)
    return cp


def kernel_coordinates(npixel, field_of_view, dl=0, dm=0, transformmatrix=None):
    """
    Returns (l,m) coordinates for generation of kernels
    in a far-field of the given size.

    If coordinate transformations are passed, they must be inverse to
    the transformations applied to the visibilities using
    visibility_shift/uvw_transform.

    :param field_of_view:
    :param npixel: Desired far-field size
    :param dl: Pattern horizontal shift (see visibility_shift)
    :param dm: Pattern vertical shift (see visibility_shift)
    :param transformmatrix: Pattern transformation matrix (see uvw_transform)
    :returns: Pair of (m,l) coordinates
    """
    
    m, l = _coordinates2(npixel) * field_of_view
    if transformmatrix is not None:
        l, m = transformmatrix[0, 0] * l + transformmatrix[1, 0] * m, transformmatrix[0, 1] * l + transformmatrix[
            1, 1] * m
    return m + dm, l + dl


def _kernel_oversample(ff, npixel, kernel_oversampling, s):
    """
    Takes a farfield pattern and creates an oversampled convolution
    function.

    If the far field size is smaller than npixel*kernel_oversampling, we will pad it. This
    essentially means we apply a sinc anti-aliasing kernel by default.

    :param ff: Far field pattern
    :param npixel:  Image size without oversampling
    :param kernel_oversampling: Factor to oversample by -- there will be kernel_oversampling x kernel_oversampling convolution arl
    :param s: Size of convolution function to extract
    :returns: Numpy array of shape [ov, ou, v, u], e.g. with sub-pixel
      offsets as the outer coordinates.
    """
    
    # Pad the far field to the required pixel size
    padff = pad_mid(ff, npixel * kernel_oversampling)
    
    # Obtain oversampled uv-grid
    af = ifft(padff)
    
    # Extract kernels
    res = [[extract_oversampled(af, x, y, kernel_oversampling, s) for x in range(kernel_oversampling)]
           for y in range(kernel_oversampling)]
    return numpy.array(res)


def _w_kernel(field_of_view, w, npixel_farfield, npixel_kernel, kernel_oversampling):
    """
    The middle s pixels of W convolution kernel. (W-KERNel-Aperture-Function)

    :param field_of_view: Field of view (directional cosines)
    :param w: Baseline distance to the projection plane
    :param npixel_farfield: Far field size. Must be at least npixel_kernel+1 if kernel_oversampling > 1, otherwise npixel_kernel.
    :param npixel_kernel: Size of convolution function to extract
    :param kernel_oversampling: Oversampling, pixels will be kernel_oversampling smaller in aperture
      plane than required to minimially sample field_of_view.

    :returns: [kernel_oversampling,kernel_oversampling,s,s] shaped oversampled convolution kernels
    """
    assert npixel_farfield > npixel_kernel or (npixel_farfield == npixel_kernel and kernel_oversampling == 1)
    return _kernel_oversample(_w_kernel_function(npixel_farfield, field_of_view, w), npixel_farfield,
                              kernel_oversampling, npixel_kernel)


def _frac_coord(npixel, kernel_oversampling, p):
    """
    Compute whole and fractional parts of coordinates, rounded to
    kernel_oversampling-th fraction of pixel size

    The fractional values are rounded to nearest 1/kernel_oversampling pixel value. At
    fractional values greater than (kernel_oversampling-0.5)/kernel_oversampling coordinates are
    roundeded to next integer index.

    :param npixel: Number of pixels in total
    :param kernel_oversampling: Fractional values to round to
    :param p: Coordinate in range [-.5,.5[
    """
    assert numpy.array(p >= -0.5).all() and numpy.array(p < 0.5).all()
    x = npixel // 2 + p * npixel
    flx = numpy.floor(x + 0.5 / kernel_oversampling)
    fracx = numpy.around((x - flx) * kernel_oversampling)
    return flx.astype(int), fracx.astype(int)


def _frac_coords(shape, kernel_oversampling, xycoords):
    """Compute grid coordinates and fractional values for convolutional
    gridding

    :param shape: (height,width) grid shape
    :param kernel_oversampling: Oversampling factor
    :param xycoords: array of (x,y) coordinates in range [-.5,.5[
    """
    h, w = shape  # NB order (height,width) to match numpy!
    x, xf = _frac_coord(w, kernel_oversampling, xycoords[:, 0])
    y, yf = _frac_coord(h, kernel_oversampling, xycoords[:, 1])
    return x, xf, y, yf


def convolutional_degrid(gcf, uvgrid, uv):
    """Convolutional degridding with frequency and polarisation independent

    Takes into account fractional `uv` coordinate values where the GCF
    is oversampled

    :param uv:
    :param gcf: Oversampled convolution kernel
    :param uvgrid:   The uv plane to de-grid from
    :returns: Array of visibilities.
    """
    kernel_oversampling, _, gh, gw = gcf.shape
    coords = _frac_coords(uvgrid.shape, kernel_oversampling, uv)
    vis = [
        numpy.sum(uvgrid[..., y - gh // 2: y + (gh + 1) // 2, x - gw // 2: x + (gw + 1) // 2] * gcf[yf, xf])
        for x, xf, y, yf in zip(*coords)
        ]
    return numpy.array(vis)


def convolutional_grid(gcf, uvgrid, uv, vis):
    """Grid after convolving with frequency and polarisation independent gcf

    Takes into account fractional `uv` coordinate values where the GCF
    is oversampled

    :param gcf: Oversampled convolution kernel
    :param uvgrid: Grid to add to
    :param uv: UVW positions
    :param vis: Visibility values
    """
    
    kernel_oversampling, _, gh, gw = gcf.shape
    coords = _frac_coords(uvgrid.shape, kernel_oversampling, uv)
    for vis, x, xf, y, yf in zip(vis, *coords):
        uvgrid[..., y - gh // 2: y + (gh + 1) // 2, x - gw // 2: x + (gw + 1) // 2] += gcf[yf, xf] * vis
