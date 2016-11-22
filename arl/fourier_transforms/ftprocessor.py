# Tim Cornwell <realtimcornwell@gmail.com>
#
"""
Functions that aid fourier transform processing. These are built on top of the core
functions in arl.fourier_transforms
"""
from astropy import units as units
from astropy import wcs
from astropy.wcs.utils import pixel_to_skycoord
from astropy.constants import c

from arl.data.data_models import *
from arl.data.parameters import get_parameter
from arl.fourier_transforms.convolutional_gridding import anti_aliasing_function, fixed_kernel_grid, \
    fixed_kernel_degrid, _kernel_oversample, weight_gridding, _w_kernel_function
from arl.fourier_transforms.fft_support import fft, ifft
from arl.image.iterators import *
from arl.util.coordinate_support import simulate_point, skycoord_to_lmn
from arl.visibility.operations import phaserotate_visibility
from arl.visibility.iterators import *

log = logging.getLogger("arl.ftprocessor")

def _shiftvis(im, vis, params):
    """Shift visibility to the FFT phase centre of the image
    
    """
    nchan, npol, ny, nx = im.data.shape
    # Convert the FFT definition of the phase center to world coordinates
    sc = pixel_to_skycoord(ny // 2, nx // 2, im.wcs)
    log.debug("Pixel (%d, %d) converts to direction %s" % ( nx//2, ny//2, sc))
    vis = phaserotate_visibility(vis, sc, params)
    return vis


def predict_2d(vis, model, kernel=None, params=None):
    """ Predict using image partitions, calling specified predict function
    
    This calls the convolutional gridding routine directly

    """
    if params is None:
        params = {}
    nchan, npol, ny, nx = model.data.shape
    if kernel is None:
        log.info("ftprocessor.predict_2d: predicting using PSWF")
        gcf = anti_aliasing_function((ny, nx))
        gcf = gcf / gcf.max()
        kernel = _kernel_oversample(gcf, nx, 8, 8)
    else:
        log.error("ftprocessor.predict_2d: unknown kernel")
    
    uvgrid = fft((model.data / gcf).astype(dtype=complex))
    cellsize = abs(model.wcs.wcs.cdelt[0]) * numpy.pi / 180.0
    # uvw is in metres, v.frequency / c.value converts to wavelengths, the cellsize converts to phase
    uvscale = cellsize * vis.frequency / c.value
    vis.data['vis'] += fixed_kernel_degrid(kernel, uvgrid, vis.data['uvw'], uvscale)
    return vis


def predict_image_partition(vis, model, predict_function=predict_2d, params=None):
    """ Predict using image partitions, calling specified predict function

    This is layered on other proaitions
    """
    if params is None:
        params = {}
    nraster = get_parameter(params, "image_partitions", 3)
    log.info("ftprocessor.predict_image_partition: predicting using %d x %d image partitions" % (nraster, nraster))
    for mpatch in raster_iter(model, nraster=nraster):
        vis.data['vis'] = predict_function(vis, mpatch, params=params).data['vis']
    return vis


def predict_fourier_partition(vis, model, predict_function=predict_2d, params=None):
    """ Predict using fourier partitions, calling specified predict function

    """
    if params is None:
        params = {}
    nraster = get_parameter(params, "fourier_partitions", 3)
    log.info("ftprocessor.predict_fourier_partition: predicting using %d x %d fourier partitions" % (nraster, nraster))
    for fpatch in raster_iter(model, nraster=nraster):
        vis.data['vis'] = predict_function(vis, fpatch, params=params).data['vis']
    return vis


def predict_wslice_partition(vis, model, predict_function=predict_2d, params=None):
    """ Predict using partitions in w

    """
    if params is None:
        params = {}
    log.info("ftprocessor.predict_wslice_partition: predicting")
    wslice = get_parameter(params, "wslice", 1000)
    for vslice in vis_wslice_iter(vis, wslice):
        predict_function(vslice, model, params=params)
    return vis


def invert_2d(vis, im, dopsf=False, kernel=None, params=None):
    """ Invert using 2D convolution function
    
    Use the image im as a template. Do PSF in a separate call.
    
    :param vis: Visibility ndarray to be inverted
    :param im: image template (not changed)
    :param sumweights: sum of weights of visibilities
    :param dopsf: Make the psf instead of the dirty image
    :param kernel: use this kernel instead of PSWF
    :param params: Parameters for processing
    
    """
    
    if params is None:
        params = {}
    nchan, npol, ny, nx = im.data.shape
    kernel = None
    gcf = 1.0
    if kernel is None:
        log.info("ftprocessor.invert_2d: Two-dimensional invert using PSWF")
        # Make the gridding convolution function the size of the image
        gcf = anti_aliasing_function((ny, nx))
        gcf = gcf / gcf.max()
        kernel = _kernel_oversample(gcf, nx, 8, 8)
    elif kernel == 'wprojection':
        log.error("ftprocessor.invert_2d: Two-dimensional invert using wprojection")
    else:
        log.error("ftprocessor.invert_2d: unknown kernel")
    
    cellsize = abs(im.wcs.wcs.cdelt[0]) * numpy.pi / 180.0
    # uvw is in metres, v.frequency / c.value converts to wavelengths, the cellsize converts to phase
    uvscale = cellsize * vis.frequency / c.value
    if dopsf:
        weights = numpy.ones_like(vis.data['vis'])
        imgrid = numpy.zeros_like(im.data, dtype='complex')
        imgrid = fixed_kernel_grid(kernel, imgrid, vis.data['uvw'], uvscale, weights, vis.data['imaging_weight'])
        imgrid = numpy.real(ifft(imgrid)) / gcf
    else:
        imgrid = numpy.zeros_like(im.data, dtype='complex')
        imgrid = fixed_kernel_grid(kernel, imgrid, vis.data['uvw'], uvscale, vis.data['vis'],
                                   vis.data['imaging_weight'])
        imgrid = numpy.real(ifft(imgrid)) / gcf
    
    return create_image_from_array(imgrid, im.wcs)


def invert_image_partition(vis, im, dopsf=False, kernel=None, invert_function=invert_2d, params=None):
    """ Predict using image partitions, calling specified predict function

    """
    
    if params is None:
        params = {}
    nraster = get_parameter(params, "image_partitions", 1)
    log.info("ftprocessor.invert_image_partition: Two-dimensional invert using %d x %d image partitions" %
             (nraster, nraster))
    i = 0
    for dpatch in raster_iter(im, nraster=nraster):
        result = invert_function(_shiftvis(dpatch, vis, params), dpatch, dopsf, params=params)
        # Ensure that we fill in the elements of dpatch instead of creating a new numpy arrray
        dpatch.data[...] = result.data[...]
        assert numpy.max(numpy.abs(dpatch.data)), "Raster image %d appears to be empty" % i
        i += 1
    assert numpy.max(numpy.abs(im.data)), "Output image appears to be empty"

    return im


def invert_fourier_partition(vis, im, dopsf=False, kernel=None, invert_function=invert_2d, params=None):
    """ Predict using fourier partitions, calling specified predict function

    """
    if params is None:
        params = {}
    nraster = get_parameter(params, "fourier_partitions", 1)
    log.info("ftprocessor.invert_fourier_partition: inverting using %d x %d fourier partitions" % (nraster, nraster))
    for dpatch in raster_iter(im, nraster=nraster):
        result = invert_function(vis, dpatch, dopsf, invert_function, params)
    
    return result


def invert_wslice_partition(vis, im, dopsf=False, kernel=None, invert_function=invert_2d, params=None):
    """ Predict using wslices

    """
    if params is None:
        params = {}
    wstep = get_parameter(params, "wstep", 1000)
    log.info("ftprocessor.invert_wslice_partition: inverting")
    for visslice in vis_wslice_iter(vis, wstep):
        result = invert_function(visslice, im, dopsf, invert_function, params)
    
    return result


def predict_skycomponent_visibility(vis: Visibility, sc: Skycomponent, params=None) -> Visibility:
    """Predict the visibility from a Skycomponent, add to existing visibility

    :param params:
    :param vis:
    :param sc:
    :returns: Visibility
    """
    if params is None:
        params = {}
    
    spectral_mode = get_parameter(params, 'spectral_mode', 'channel')
    
    assert_same_chan_pol(vis, sc)
    
    l, m, n = skycoord_to_lmn(sc.direction, vis.phasecentre)
    log.info('fourier_transforms.predict_visibility: Cartesian representation of component = (%f, %f, %f)'
              % (l, m, n))
    # The data column has vis:[row,nchan,npol], uvw:[row,3]
    if spectral_mode == 'channel':
        for channel in range(sc.nchan):
            uvw = vis.uvw_lambda(channel)
            phasor = simulate_point(uvw, l, m)
            for pol in range(sc.npol):
                vis.vis[:, channel, pol] += sc.flux[channel, pol] * phasor
    else:
        raise NotImplementedError("mode %s not supported" % spectral_mode)
    
    return vis


def calculate_delta_residual(deltamodel, vis, params):
    """Calculate the delta in residual for a given delta in model
    
    This calculation does not require the original visibilities.
    """
    return deltamodel


def weight_visibility(vis, im, params=None):
    """ Reweight the visibility data using a selected algorithm

    Imaging uses the column "imaging_weight" when imaging. This function sets that column using a
    variety of algorithms
    
    :param vis:
    :param im:
    :param params: Dictionary containing parameters
    :returns: Configuration
    """
    
    if params is None:
        params = {}
    cellsize = abs(im.wcs.wcs.cdelt[0]) * numpy.pi / 180.0
    # uvw is in metres, v.frequency / c.value converts to wavelengths, the cellsize converts to phase
    weighting = get_parameter(params, "weighting", "uniform")
    if weighting == 'uniform':
        uvscale = cellsize * vis.frequency / c.value
        vis.data['imaging_weight'] = weight_gridding(im.data.shape, vis.data['uvw'], uvscale, vis.data['weight'],
                                                     params)
    elif weighting == 'natural':
        vis.data['imaging_weight'] = vis.data['weight']
    else:
        log.error("Unknown gridding algorithm %s" % weighting)
    
    return vis


def create_wcs_from_visibility(vis, params=None):
    """Make a world coordinate system from params and Visibility

    :param vis:
    :param params: keyword=value parameters
    :returns: WCS
    """
    if params is None:
        params = {}
    log.info("fourier_transforms.create_wcs_from_visibility: Parsing parameters to get definition of WCS")
    imagecentre = get_parameter(params, "imagecentre", vis.phasecentre)
    phasecentre = get_parameter(params, "phasecentre", vis.phasecentre)
    reffrequency = get_parameter(params, "reffrequency", numpy.min(vis.frequency)) * units.Hz
    deffaultbw = vis.frequency[0]
    if len(vis.frequency) > 1:
        deffaultbw = vis.frequency[1] - vis.frequency[0]
    channelwidth = get_parameter(params, "channelwidth", deffaultbw) * units.Hz
    log.info("fourier_transforms.create_wcs_from_visibility: Defining Image at %s, frequency %s, and bandwidth %s"
              % (imagecentre, reffrequency, channelwidth))
    
    npixel = get_parameter(params, "npixel", 512)
    uvmax = (numpy.abs(vis.data['uvw']).max() * numpy.max(vis.frequency) / c).value
    log.info("create_wcs_from_visibility: uvmax = %f lambda" % uvmax)
    criticalcellsize = 1.0 / (uvmax * 2.0)
    log.info("create_wcs_from_visibility: Critical cellsize = %f radians, %f degrees" % (
        criticalcellsize, criticalcellsize * 180.0 / numpy.pi))
    cellsize = get_parameter(params, "cellsize", 0.5 * criticalcellsize)
    log.info("create_wcs_from_visibility: Cellsize          = %f radians, %f degrees" % (cellsize,
                                                                                          cellsize * 180.0 / numpy.pi))
    if cellsize > criticalcellsize:
        log.info("Resetting cellsize %f radians to criticalcellsize %f radians" % (cellsize, criticalcellsize))
        cellsize = criticalcellsize
    
    npol = 4
    # Beware of python indexing order! wcs and the array have opposite ordering
    shape = [len(vis.frequency), npol, npixel, npixel]
    w = wcs.WCS(naxis=4)
    # The negation in the longitude is needed by definition of RA, DEC
    w.wcs.cdelt = [-cellsize * 180.0 / numpy.pi, cellsize * 180.0 / numpy.pi, 1.0, channelwidth.value]
    w.wcs.crpix = [npixel // 2 + 1, npixel // 2 + 1, 1.0, 0.0]
    w.wcs.ctype = ["RA---SIN", "DEC--SIN", 'STOKES', 'FREQ']
    w.wcs.crval = [phasecentre.ra.value, phasecentre.dec.value, 1.0, reffrequency.value]
    w.naxis = 4
    
    w.wcs.radesys = get_parameter(params, 'frame', 'ICRS')
    w.wcs.equinox = get_parameter(params, 'equinox', 2000.0)
    
    return shape, reffrequency, cellsize, w, imagecentre


def create_image_from_visibility(vis, params=None):
    """Make an empty imagefrom params and Visibility

    :param vis:
    :param params: keyword=value parameters
    :returns: WCS
    """
    shape, _, _, w, _ = create_wcs_from_visibility(vis, params=params)
    return create_image_from_array(numpy.zeros(shape), wcs=w)


def create_w_term_image(vis, w=None, params=None):
    """Create an image with a w term phase term in it
    
    """
    if w is None:
        w = numpy.median(numpy.abs(vis.data['uvw'][:,2]))
        log.info('ftprocessor.create_w_term_image: Creating w term image for median w %f' % w)
        
    im = create_image_from_visibility(vis, params)
    cellsize = abs(im.wcs.wcs.cdelt[0]) * numpy.pi / 180.0
    _, _, _, npixel = im.data.shape
    im.data = _w_kernel_function(npixel, npixel * cellsize, w=w)

    fresnel = w * (0.5 * npixel * cellsize)**2
    log.info('ftprocessor.create_w_term_image: Fresnel number for this field of view and sampling = %.2f' % (fresnel))

    return im