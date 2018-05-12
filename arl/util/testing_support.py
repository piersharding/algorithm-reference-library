"""
Functions that aid testing in various ways. A typical use would be::

        lowcore = create_named_configuration('LOWBD2-CORE')
        times = numpy.linspace(-3, +3, 13) * (numpy.pi / 12.0)
        
        frequency = numpy.array([1e8])
        channel_bandwidth = numpy.array([1e7])
        
        # Define the component and give it some polarisation and spectral behaviour
        f = numpy.array([100.0])
        flux = numpy.array([f])
        
        phasecentre = SkyCoord(ra=+15.0 * u.deg, dec=-35.0 * u.deg, frame='icrs', equinox='J2000')
        compabsdirection = SkyCoord(ra=17.0 * u.deg, dec=-36.5 * u.deg, frame='icrs', equinox='J2000')
        
        comp = create_skycomponent(flux=flux, frequency=frequency, direction=compabsdirection,
                                        polarisation_frame=PolarisationFrame('stokesI'))
        image_graph = create_test_image)(frequency=frequency, phasecentre=phasecentre,
                                                      cellsize=0.001,
                                                      polarisation_frame=PolarisationFrame('stokesI')
        
        vis = create_visibility(lowcore, times=times, frequency=frequency,
                                     channel_bandwidth=channel_bandwidth,
                                     phasecentre=phasecentre, weight=1,
                                     polarisation_frame=PolarisationFrame('stokesI'),
                                     integration_time=1.0)

"""

import csv
import logging
from typing import List

import astropy.units as u
import numpy
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import pixel_to_skycoord
from scipy import interpolate

from arl.calibration.calibration_control import create_calibration_controls
from arl.calibration.operations import create_gaintable_from_blockvisibility, apply_gaintable
from arl.data.data_models import Configuration, Image, GainTable, Skycomponent
from arl.data.parameters import arl_path
from arl.data.parameters import get_parameter
from arl.data.polarisation import PolarisationFrame
from arl.image.operations import import_image_from_fits, create_image_from_array, \
    reproject_image, create_empty_image_like, qa_image
from arl.imaging import predict_timeslice, predict_skycomponent_visibility, create_image_from_visibility, \
    advise_wide_field
from arl.skycomponent.operations import create_skycomponent, insert_skycomponent, apply_beam_to_skycomponent
from arl.util.coordinate_support import xyz_at_latitude
from arl.visibility.base import create_blockvisibility, create_visibility
from arl.visibility.coalesce import convert_visibility_to_blockvisibility

log = logging.getLogger(__name__)


def create_configuration_from_file(antfile: str, location: EarthLocation = None,
                                   mount: str = 'altaz',
                                   names: str = "%d", frame: str = 'local',
                                   diameter=35.0,
                                   rmax=None) -> Configuration:
    """ Define from a file

    :param names:
    :param antfile: Antenna file name
    :param name: Name of array e.g. 'LOWBD2'
    :param location:
    :param mount: mount type: 'altaz', 'xy'
    :param frame: 'local' | 'global'
    :param diameter: Effective diameter of station or antenna
    :param meta: Any meta info
    :return: Configuration
    """
    antxyz = numpy.genfromtxt(antfile, delimiter=",")
    assert antxyz.shape[1] == 3, ("Antenna array has wrong shape %s" % antxyz.shape)
    if frame == 'local':
        latitude = location.geodetic[1].to(u.rad).value
        antxyz = xyz_at_latitude(antxyz, latitude)
    if rmax is not None:
        lantxyz = antxyz - numpy.average(antxyz, axis=0)
        r = numpy.sqrt(lantxyz[:, 0] ** 2 + lantxyz[:, 1] ** 2 + lantxyz[:, 2] ** 2)
        antxyz = antxyz[r < rmax]
        log.debug('create_configuration_from_file: Maximum radius %.1f m includes %d antennas/stations' %
                  (rmax, antxyz.shape[0]))
    
    nants = antxyz.shape[0]
    anames = [names % ant for ant in range(nants)]
    mounts = numpy.repeat(mount, nants)
    fc = Configuration(location=location, names=anames, mount=mounts, xyz=antxyz, frame=frame,
                       diameter=diameter)
    return fc


def create_LOFAR_configuration(antfile: str, meta: dict = None) -> Configuration:
    """ Define from the LOFAR configuration file

    :param antfile:
    :param meta:
    :return: Configuration
    """
    antxyz = numpy.genfromtxt(antfile, skip_header=2, usecols=[1, 2, 3], delimiter=",")
    nants = antxyz.shape[0]
    assert antxyz.shape[1] == 3, "Antenna array has wrong shape %s" % antxyz.shape
    anames = numpy.genfromtxt(antfile, dtype='str', skip_header=2, usecols=[0], delimiter=",")
    mounts = numpy.repeat('XY', nants)
    location = EarthLocation(x=[3826923.9] * u.m, y=[460915.1] * u.m, z=[5064643.2] * u.m)
    fc = Configuration(location=location, names=anames, mount=mounts, xyz=antxyz, frame='global',
                       diameter=35.0)
    return fc


def create_named_configuration(name: str = 'LOWBD2', **kwargs) -> Configuration:
    """ Standard configurations e.g. LOWBD2, MIDBD2

    :param name: name of Configuration LOWBD2, LOWBD1, LOFAR, VLAA
    :param rmax: Maximum distance of station from the average (m)
    :return:
    
    For LOWBD2, setting rmax gives the following number of stations
    100.0       13
    300.0       94
    1000.0      251
    3000.0      314
    10000.0     398
    30000.0     476
    100000.0    512
    """
    
    if name == 'LOWBD2':
        location = EarthLocation(lon="116.4999", lat="-26.7000", height=300.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/LOWBD2.csv"),
                                            location=location, mount='xy', names='LOWBD2_%d',
                                            diameter=35.0, **kwargs)
    elif name == 'LOWBD1':
        location = EarthLocation(lon="116.4999", lat="-26.7000", height=300.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/LOWBD1.csv"),
                                            location=location, mount='xy', names='LOWBD1_%d',
                                            diameter=35.0, **kwargs)
    elif name == 'LOWBD2-CORE':
        location = EarthLocation(lon="116.4999", lat="-26.7000", height=300.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/LOWBD2-CORE.csv"),
                                            location=location, mount='xy', names='LOWBD2_%d',
                                            diameter=35.0, **kwargs)
    elif name == 'LOFAR':
        assert get_parameter(kwargs, "meta", False) is False
        fc = create_LOFAR_configuration(antfile=arl_path("data/configurations/LOFAR.csv"))
    elif name == 'VLAA':
        location = EarthLocation(lon="-107.6184", lat="34.0784", height=2124.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/VLA_A_hor_xyz.csv"),
                                            location=location,
                                            mount='altaz',
                                            names='VLA_%d',
                                            diameter=25.0, **kwargs)
    elif name == 'VLAA_north':
        location = EarthLocation(lon="-107.6184", lat="90.000", height=2124.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/VLA_A_hor_xyz.csv"),
                                            location=location,
                                            mount='altaz',
                                            names='VLA_%d',
                                            diameter=25.0, **kwargs)
    else:
        raise ValueError("No such Configuration %s" % name)
    return fc


def create_test_image(canonical=True, cellsize=None, frequency=None, channel_bandwidth=None,
                      phasecentre=None, polarisation_frame=PolarisationFrame("stokesI")) -> Image:
    """Create a useful test image

    This is the test image M31 widely used in ALMA and other simulations. It is actually part of an Halpha region in
    M31.

    :param canonical: Make the image into a 4 dimensional image
    :param cellsize:
    :param frequency: Frequency (array) in Hz
    :param channel_bandwidth: Channel bandwidth (array) in Hz
    :param phasecentre: Phase centre of image (SkyCoord)
    :param polarisation_frame: Polarisation frame
    :return: Image
    """
    if frequency is None:
        frequency = [1e8]
    im = import_image_from_fits(arl_path("data/models/M31.MOD"))
    if canonical:
        
        if polarisation_frame is None:
            im.polarisation_frame = PolarisationFrame("stokesI")
        elif isinstance(polarisation_frame, PolarisationFrame):
            im.polarisation_frame = polarisation_frame
        else:
            raise ValueError("polarisation_frame is not valid")
        
        im = replicate_image(im, frequency=frequency, polarisation_frame=im.polarisation_frame)
        if cellsize is not None:
            im.wcs.wcs.cdelt[0] = -180.0 * cellsize / numpy.pi
            im.wcs.wcs.cdelt[1] = +180.0 * cellsize / numpy.pi
        if frequency is not None:
            im.wcs.wcs.crval[3] = frequency[0]
        if channel_bandwidth is not None:
            im.wcs.wcs.cdelt[3] = channel_bandwidth[0]
        else:
            if len(frequency) > 1:
                im.wcs.wcs.cdelt[3] = frequency[1] - frequency[0]
            else:
                im.wcs.wcs.cdelt[3] = 0.001 * frequency[0]
        im.wcs.wcs.radesys = 'ICRS'
        im.wcs.wcs.equinox = 2000.00
    
    if phasecentre is not None:
        im.wcs.wcs.crval[0] = phasecentre.ra.deg
        im.wcs.wcs.crval[1] = phasecentre.dec.deg
        # WCS is 1 relative
        im.wcs.wcs.crpix[0] = im.data.shape[3] // 2 + 1
        im.wcs.wcs.crpix[1] = im.data.shape[2] // 2 + 1
    
    return im


def create_low_test_image_from_s3(npixel=16384, polarisation_frame=PolarisationFrame("stokesI"), cellsize=0.000015,
                                  frequency=numpy.array([1e8]), channel_bandwidth=numpy.array([1e6]),
                                  phasecentre=None, fov=20) -> Image:
    """Create LOW test image from S3

    The input catalog was generated at http://s-cubed.physics.ox.ac.uk/s3_sex using the following query::
        Database: s3_sex
        SQL: select * from Galaxies where (pow(10,itot_151)*1000 > 1.0) and (right_ascension between -5 and 5) and (declination between -5 and 5);;

    Number of rows returned: 29966

    There are three possible tables to use::

        data/models/S3_151MHz_10deg.csv, use fov=10
        data/models/S3_151MHz_20deg.csv, use fov=20
        data/models/S3_151MHz_40deg.csv, use fov=40

    The component spectral index is calculated from the 610MHz and 151MHz, and then calculated for the specified
    frequencies.

    If polarisation_frame is not stokesI then the image will a polarised axis but the values will be zero.

    :param npixel: Number of pixels
    :param polarisation_frame: Polarisation frame (default PolarisationFrame("stokesI"))
    :param cellsize: cellsize in radians
    :param frequency:
    :param channel_bandwidth: Channel width (Hz)
    :param phasecentre: phasecentre (SkyCoord)
    :param fov: fov table to use
    :return: Image
    """
    
    ras = []
    decs = []
    fluxes = []
    
    if phasecentre is None:
        phasecentre = SkyCoord(ra=+180.0 * u.deg, dec=-60.0 * u.deg, frame='icrs', equinox='J2000')
    
    if polarisation_frame is None:
        polarisation_frame = PolarisationFrame("I")
    
    npol = polarisation_frame.npol
    
    nchan = len(frequency)
    
    shape = [nchan, npol, npixel, npixel]
    w = WCS(naxis=4)
    # The negation in the longitude is needed by definition of RA, DEC
    w.wcs.cdelt = [-cellsize * 180.0 / numpy.pi, cellsize * 180.0 / numpy.pi, 1.0, channel_bandwidth[0]]
    w.wcs.crpix = [npixel // 2 + 1, npixel // 2 + 1, 1.0, 1.0]
    w.wcs.ctype = ["RA---SIN", "DEC--SIN", 'STOKES', 'FREQ']
    w.wcs.crval = [phasecentre.ra.deg, phasecentre.dec.deg, 1.0, frequency[0]]
    w.naxis = 4
    
    w.wcs.radesys = 'ICRS'
    w.wcs.equinox = 2000.0
    
    model = create_image_from_array(numpy.zeros(shape), w, polarisation_frame=polarisation_frame)
    
    assert fov in [10, 20, 40], "Field of view invalid: use one of %s" % ([10, 20, 40])
    with open(arl_path('data/models/S3_151MHz_%ddeg.csv' % (fov))) as csvfile:
        readCSV = csv.reader(csvfile, delimiter=',')
        r = 0
        for row in readCSV:
            # Skip first row
            if r > 0:
                ra = float(row[4]) + phasecentre.ra.deg
                dec = float(row[5]) + phasecentre.dec.deg
                alpha = (float(row[10]) - float(row[9])) / numpy.log10(610.0 / 151.0)
                flux = numpy.power(10, float(row[9])) * numpy.power(frequency / 1.51e8, alpha)
                ras.append(ra)
                decs.append(dec)
                fluxes.append(flux)
            r += 1
    
    csvfile.close()
    
    p = w.sub(2).wcs_world2pix(numpy.array(ras), numpy.array(decs), 1)
    total_flux = numpy.sum(fluxes)
    fluxes = numpy.array(fluxes)
    ip = numpy.round(p).astype('int')
    ok = numpy.where((0 <= ip[0, :]) & (npixel > ip[0, :]) & (0 <= ip[1, :]) & (npixel > ip[1, :]))[0]
    ps = ip[:, ok]
    fluxes = fluxes[ok]
    actual_flux = numpy.sum(fluxes)
    
    log.info('create_low_test_image_from_s3: %d sources inside the image' % (ps.shape[1]))
    
    log.info('create_low_test_image_from_s3: average channel flux in S3 model = %.3f, actual average channel flux in '
             'image = %.3f' % (total_flux / float(nchan), actual_flux / float(nchan)))
    for chan in range(nchan):
        for iflux, flux in enumerate(fluxes):
            model.data[chan, 0, ps[1, iflux], ps[0, iflux]] = flux[chan]
    
    return model


def create_low_test_image_composite(npixel=16384, polarisation_frame=PolarisationFrame("stokesI"),
                                    cellsize=0.000015,
                                    frequency=numpy.array([1e8]), channel_bandwidth=numpy.array([1e6]),
                                    phasecentre=None, kind='cubic', fov=20, threshold=0.050) -> Image:
    """Create LOW test image from merge of S3 and GLEAM test images
    
    :param npixel: Number of pixels
    :param polarisation_frame: Polarisation frame (default PolarisationFrame("stokesI"))
    :param cellsize: cellsize in radians
    :param frequency:
    :param channel_bandwidth: Channel width (Hz)
    :param phasecentre: phasecentre (SkyCoord)
    :param kind: Kind of interpolation (see scipy.interpolate.interp1d) Default: cubic
    :param fov: Field of view to use in S3
    :param threshold: Below threshold S3, above threshold GLEAM
    :return: Image
    """
    img = create_low_test_image_from_gleam(npixel=npixel, polarisation_frame=polarisation_frame,
                                           cellsize=cellsize,
                                           frequency=frequency, channel_bandwidth=channel_bandwidth,
                                           phasecentre=phasecentre, kind=kind)
    img.data[img.data < threshold] = 0.0
    ims3 = create_low_test_image_from_s3(npixel=npixel, polarisation_frame=polarisation_frame,
                                         cellsize=cellsize,
                                         frequency=frequency, channel_bandwidth=channel_bandwidth,
                                         phasecentre=phasecentre, fov=fov)
    ims3.data[ims3.data >= threshold] = 0.0
    
    ims3.data += img.data
    return ims3


def create_low_test_image_from_gleam(npixel=512, polarisation_frame=PolarisationFrame("stokesI"), cellsize=0.000015,
                                     frequency=numpy.array([1e8]), channel_bandwidth=numpy.array([1e6]),
                                     phasecentre=None, kind='cubic', applybeam=False, flux_limit=0.1,
                                     radius=None, insert_method='Nearest') -> Image:
    """Create LOW test image from the GLEAM survey

    Stokes I is estimated from a cubic spline fit to the measured fluxes. The polarised flux is always zero.
    
    See http://www.mwatelescope.org/science/gleam-survey The catalog is available from Vizier.
    
    VIII/100   GaLactic and Extragalactic All-sky MWA survey  (Hurley-Walker+, 2016)

    GaLactic and Extragalactic All-sky Murchison Wide Field Array (GLEAM) survey. I: A low-frequency extragalactic
    catalogue. Hurley-Walker N., et al., Mon. Not. R. Astron. Soc., 464, 1146-1167 (2017), 2017MNRAS.464.1146H

    :param npixel: Number of pixels
    :param polarisation_frame: Polarisation frame (default PolarisationFrame("stokesI"))
    :param cellsize: cellsize in radians
    :param frequency:
    :param channel_bandwidth: Channel width (Hz)
    :param phasecentre: phasecentre (SkyCoord)
    :param kind: Kind of interpolation (see scipy.interpolate.interp1d) Default: linear
    :return: Image
    
    """
    
    if phasecentre is None:
        phasecentre = SkyCoord(ra=+15.0 * u.deg, dec=-35.0 * u.deg, frame='icrs', equinox='J2000')
    
    if radius is None:
        radius = npixel * cellsize / numpy.sqrt(2.0)
    
    sc = create_low_test_skycomponents_from_gleam(flux_limit=flux_limit, polarisation_frame=polarisation_frame,
                                                  frequency=frequency, phasecentre=phasecentre,
                                                  kind=kind, radius=radius)
    if polarisation_frame is None:
        polarisation_frame = PolarisationFrame("stokesI")
    
    npol = polarisation_frame.npol
    nchan = len(frequency)
    shape = [nchan, npol, npixel, npixel]
    w = WCS(naxis=4)
    # The negation in the longitude is needed by definition of RA, DEC
    w.wcs.cdelt = [-cellsize * 180.0 / numpy.pi, cellsize * 180.0 / numpy.pi, 1.0, channel_bandwidth[0]]
    w.wcs.crpix = [npixel // 2 + 1, npixel // 2 + 1, 1.0, 1.0]
    w.wcs.ctype = ["RA---SIN", "DEC--SIN", 'STOKES', 'FREQ']
    w.wcs.crval = [phasecentre.ra.deg, phasecentre.dec.deg, 1.0, frequency[0]]
    w.naxis = 4
    w.wcs.radesys = 'ICRS'
    w.wcs.equinox = 2000.0
    
    model = create_image_from_array(numpy.zeros(shape), w, polarisation_frame=polarisation_frame)
    
    model = insert_skycomponent(model, sc, insert_method=insert_method)
    if applybeam:
        beam = create_low_test_beam(model)
        model.data[...] *= beam.data[...]
    
    log.info(qa_image(model, context='create_low_test_image_from_gleam'))
    
    return model


def create_low_test_skycomponents_from_gleam(flux_limit=0.1, polarisation_frame=PolarisationFrame("stokesI"),
                                             frequency=numpy.array([1e8]), kind='cubic', phasecentre=None,
                                             radius=1.0) \
        -> List[Skycomponent]:
    """Create sky components from the GLEAM survey

    Stokes I is estimated from a cubic spline fit to the measured fluxes. The polarised flux is always zero.
    
    See http://www.mwatelescope.org/science/gleam-survey The catalog is available from Vizier.
    
    VIII/100   GaLactic and Extragalactic All-sky MWA survey  (Hurley-Walker+, 2016)

    GaLactic and Extragalactic All-sky Murchison Wide Field Array (GLEAM) survey. I: A low-frequency extragalactic
    catalogue. Hurley-Walker N., et al., Mon. Not. R. Astron. Soc., 464, 1146-1167 (2017), 2017MNRAS.464.1146H


    :rtype: Union[None, List[arl.data.data_models.Skycomponent], List]
    :param flux_limit: Only write components brighter than this (Jy)
    :param polarisation_frame: Polarisation frame (default PolarisationFrame("stokesI"))
    :param frequency: Frequencies at which the flux will be estimated
    :param kind: Kind of interpolation (see scipy.interpolate.interp1d) Default: linear
    :param phasecentre: Desired phase centre (SkyCoord) default None implies all sources
    :param radius: Radius of sources selected around phasecentre (default 1.0 rad)
    :return: List of Skycomponents
    """
    
    fitsfile = arl_path("data/models/GLEAM_EGC.fits")
    
    rad2deg = 180.0 / numpy.pi
    decmin = phasecentre.dec.to('deg').value - rad2deg * radius / 2.0
    decmax = phasecentre.dec.to('deg').value + rad2deg * radius / 2.0
    
    hdulist = fits.open(fitsfile, lazy_load_hdus=False)
    recs = hdulist[1].data[0].array
    
    # Do the simple forms of filtering in pyfits. Filtering on radious is done below.
    fluxes = recs['peak_flux_wide']
    
    mask = fluxes > flux_limit
    filtered_recs = recs[mask]
    
    decs = filtered_recs['DEJ2000']
    mask = decs > decmin
    filtered_recs = filtered_recs[mask]
    
    decs = filtered_recs['DEJ2000']
    mask = decs < decmax
    filtered_recs = filtered_recs[mask]
    
    ras = filtered_recs['RAJ2000']
    decs = filtered_recs['DEJ2000']
    names = filtered_recs['Name']
    
    if polarisation_frame is None:
        polarisation_frame = PolarisationFrame("stokesI")
    
    npol = polarisation_frame.npol
    
    nchan = len(frequency)
    
    # For every source, we read all measured fluxes and interpolate to the
    # required frequencies
    gleam_freqs = numpy.array([76, 84, 92, 99, 107, 115, 122, 130, 143, 151, 158, 166, 174, 181, 189, 197, 204,
                               212, 220, 227])
    gleam_flux_freq = numpy.zeros([len(names), len(gleam_freqs)])
    for i, f in enumerate(gleam_freqs):
        gleam_flux_freq[:, i] = filtered_recs['int_flux_%03d' % (f)][:]
    
    skycomps = []
    
    for isource, name in enumerate(names):
        direction = SkyCoord(ra=ras[isource] * u.deg, dec=decs[isource] * u.deg)
        if phasecentre is None or direction.separation(phasecentre).to('rad').value < radius:
            
            fint = interpolate.interp1d(gleam_freqs * 1.0e6, gleam_flux_freq[isource, :], kind=kind)
            flux = numpy.zeros([nchan, npol])
            flux[:, 0] = fint(frequency)
            if not numpy.isnan(flux).any():
                skycomps.append(Skycomponent(direction=direction, flux=flux, frequency=frequency,
                                             name=name, shape='Point',
                                             polarisation_frame=polarisation_frame))
    
    log.info('create_low_test_skycomponents_from_gleam: %d sources above flux limit %.3f' % (len(skycomps), flux_limit))
    
    hdulist.close()
    
    return skycomps


def create_low_test_beam(model: Image) -> Image:
    """Create a test power beam for LOW using an image from OSKAR

    :param model: Template image
    :return: Image
    """
    
    beam = import_image_from_fits(arl_path('data/models/SKA1_LOW_beam.fits'))
    
    # Scale the image cellsize to account for the different in frequencies. Eventually we will want to
    # use a frequency cube
    log.info("create_low_test_beam: primary beam is defined at %.3f MHz" % (beam.wcs.wcs.crval[2] * 1e-6))
    
    nchan, npol, ny, nx = model.shape
    
    # We need to interpolate each frequency channel separately. The beam is assumed to just scale with
    # frequency.
    
    reprojected_beam = create_empty_image_like(model)
    
    for chan in range(nchan):
        
        model2dwcs = model.wcs.sub(2).deepcopy()
        model2dshape = [model.shape[2], model.shape[3]]
        beam2dwcs = beam.wcs.sub(2).deepcopy()
        
        # The frequency axis is the second to last in the beam
        frequency = model.wcs.sub(['spectral']).wcs_pix2world([chan], 0)[0]
        fscale = beam.wcs.wcs.crval[2] / frequency
        
        beam2dwcs.wcs.cdelt = fscale * beam.wcs.sub(2).wcs.cdelt
        beam2dwcs.wcs.crpix = beam.wcs.sub(2).wcs.crpix
        beam2dwcs.wcs.crval = model.wcs.sub(2).wcs.crval
        beam2dwcs.wcs.ctype = model.wcs.sub(2).wcs.ctype
        model2dwcs.wcs.crpix = [model.shape[2] // 2 + 1, model.shape[3] // 2 + 1]
        
        beam2d = create_image_from_array(beam.data[0, 0, :, :], beam2dwcs, model.polarisation_frame)
        reprojected_beam2d, footprint = reproject_image(beam2d, model2dwcs, shape=model2dshape)
        assert numpy.max(footprint.data) > 0.0, "No overlap between beam and model"
        
        reprojected_beam2d.data *= reprojected_beam2d.data
        reprojected_beam2d.data[footprint.data <= 0.0] = 0.0
        for pol in range(npol):
            reprojected_beam.data[chan, pol, :, :] = reprojected_beam2d.data[:, :]
    
    return reprojected_beam


def replicate_image(im: Image, polarisation_frame=PolarisationFrame('stokesI'), frequency=numpy.array([1e8])) \
        -> Image:
    """ Make a new canonical shape Image, extended along third and fourth axes by replication.

    The order of the data is [chan, pol, dec, ra]


    :param frequency:
    :param im:
    :param polarisation_frame: Polarisation_frame
    :param nchan: Number of spectral channels
    :return: Image
    """
    
    if len(im.data.shape) == 2:
        fim = Image()
        
        newwcs = WCS(naxis=4)
        
        newwcs.wcs.crpix = [im.wcs.wcs.crpix[0] + 1.0, im.wcs.wcs.crpix[1] + 1.0, 1.0, 1.0]
        newwcs.wcs.cdelt = [im.wcs.wcs.cdelt[0], im.wcs.wcs.cdelt[1], 1.0, 1.0]
        newwcs.wcs.crval = [im.wcs.wcs.crval[0], im.wcs.wcs.crval[1], 1.0, frequency[0]]
        newwcs.wcs.ctype = [im.wcs.wcs.ctype[0], im.wcs.wcs.ctype[1], 'STOKES', 'FREQ']
        
        nchan = len(frequency)
        npol = polarisation_frame.npol
        fim.polarisation_frame = polarisation_frame
        
        fim.wcs = newwcs
        fshape = [nchan, npol, im.data.shape[1], im.data.shape[0]]
        fim.data = numpy.zeros(fshape)
        log.info("replicate_image: replicating shape %s to %s" % (im.data.shape, fim.data.shape))
        for i3 in range(nchan):
            fim.data[i3, 0, :, :] = im.data[:, :]
        return fim
    else:
        return im


def create_blockvisibility_iterator(config: Configuration, times: numpy.array, frequency: numpy.array,
                                    channel_bandwidth, phasecentre: SkyCoord, weight: float = 1,
                                    polarisation_frame=PolarisationFrame('stokesI'), integration_time=1.0,
                                    number_integrations=1, predict=predict_timeslice, model=None, components=None,
                                    phase_error=0.0, amplitude_error=0.0, sleep=0.0, **kwargs):
    """ Create a sequence of Visibilities and optionally predicting and coalescing

    This is useful mainly for performing large simulations. Do something like::
    
        vis_iter = create_blockvisibility_iterator(config, times, frequency, channel_bandwidth, phasecentre=phasecentre,
                                              weight=1.0, integration_time=30.0, number_integrations=3)

        for i, vis in enumerate(vis_iter):
        if i == 0:
            fullvis = vis
        else:
            fullvis = append_visibility(fullvis, vis)


    :param config: Configuration of antennas
    :param times: hour angles in radians
    :param frequency: frequencies (Hz] Shape [nchan]
    :param weight: weight of a single sample
    :param phasecentre: phasecentre of observation
    :param npol: Number of polarizations
    :param integration_time: Integration time ('auto' or value in s)
    :param number_integrations: Number of integrations to be created at each time.
    :param model: Model image to be inserted
    :param components: Components to be inserted
    :param sleep_time: Time to sleep between yields
    :return: Visibility

    """
    for time in times:
        actualtimes = time + numpy.arange(0, number_integrations) * integration_time * numpy.pi / 43200.0
        bvis = create_blockvisibility(config, actualtimes, frequency=frequency, phasecentre=phasecentre, weight=weight,
                                      polarisation_frame=polarisation_frame, integration_time=integration_time,
                                      channel_bandwidth=channel_bandwidth)
        
        if model is not None:
            vis = predict(bvis, model, **kwargs)
            bvis = convert_visibility_to_blockvisibility(vis)
        
        if components is not None:
            bvis = predict_skycomponent_visibility(bvis, components)
        
        # Add phase errors
        if phase_error > 0.0 or amplitude_error > 0.0:
            gt = create_gaintable_from_blockvisibility(bvis)
            gt = simulate_gaintable(gt=gt, phase_error=phase_error, amplitude_error=amplitude_error)
            bvis = apply_gaintable(bvis, gt)
        
        import time
        time.sleep(sleep)
        
        yield bvis


def simulate_gaintable(gt: GainTable, phase_error=0.1, amplitude_error=0.0, smooth_channels=1,
                       leakage=0.0, seed=180555, **kwargs) -> GainTable:
    """ Simulate a gain table
    
    :type gt: GainTable
    :param phase_error: std of normal distribution, zero mean
    :param amplitude_error: std of log normal distribution
    :param leakage: std of cross hand leakage
    :param seed: Seed for random numbers def: 180555
    :param smooth_channels: Use bspline over smooth_channels
    :param kwargs:
    :return: Gaintable
    
    """
    
    def moving_average(a, n=3):
        return numpy.convolve(a, numpy.ones((n,)) / n, mode='valid')
    
    numpy.random.seed(seed)
    
    log.debug("simulate_gaintable: Simulating amplitude error = %.4f, phase error = %.4f"
              % (amplitude_error, phase_error))
    amps = 1.0
    phases = 1.0
    ntimes, nant, nchan, nrec, _ = gt.data['gain'].shape
    if phase_error > 0.0:
        phases = numpy.zeros(gt.data['gain'].shape)
        for time in range(ntimes):
            for ant in range(nant):
                phase = numpy.random.normal(0, phase_error, nchan + int(smooth_channels) - 1)
                if smooth_channels > 1:
                    phase = moving_average(phase, smooth_channels)
                phases[time, ant, ...] = phase[..., numpy.newaxis, numpy.newaxis]
    
    if amplitude_error > 0.0:
        amps = numpy.ones(gt.data['gain'].shape, dtype='complex')
        for time in range(ntimes):
            for ant in range(nant):
                amp = numpy.random.lognormal(mean=0.0, sigma=amplitude_error, size=nchan + int(smooth_channels) - 1)
                if smooth_channels > 1:
                    amp = moving_average(amp, smooth_channels)
                    amp = amp / numpy.average(amp)
                amps[time, ant, ...] = amp[..., numpy.newaxis, numpy.newaxis]
    
    gt.data['gain'] = amps * numpy.exp(0 + 1j * phases)
    nrec = gt.data['gain'].shape[-1]
    if nrec > 1:
        if leakage > 0.0:
            leak = numpy.random.normal(0, leakage, gt.data['gain'][..., 0, 0].shape) + 1j * \
                numpy.random.normal(0, leakage, gt.data['gain'][..., 0, 0].shape)
            gt.data['gain'][..., 0, 1] = gt.data['gain'][..., 0, 0] * leak
            leak = numpy.random.normal(0, leakage, gt.data['gain'][..., 1, 1].shape) + 1j * \
                numpy.random.normal(0, leakage, gt.data['gain'][..., 1, 1].shape)
            gt.data['gain'][..., 1, 0] = gt.data['gain'][..., 1, 1] * leak
        else:
            gt.data['gain'][..., 0, 1] = 0.0
            gt.data['gain'][..., 1, 0] = 0.0
    
    return gt


def ingest_unittest_visibility(config, frequency, channel_bandwidth, times, vis_pol, phasecentre, block=False):
    if block:
        vt = create_blockvisibility(config, times, frequency, channel_bandwidth=channel_bandwidth,
                                    phasecentre=phasecentre, weight=1.0, polarisation_frame=vis_pol)
    else:
        vt = create_visibility(config, times, frequency, channel_bandwidth=channel_bandwidth,
                               phasecentre=phasecentre, weight=1.0, polarisation_frame=vis_pol)
    vt.data['vis'][...] = 0.0
    return vt


def create_unittest_components(model, flux):
    # Fill the visibility with exactly computed point sources.
    spacing_pixels = 512 // 8
    log.info('Spacing in pixels = %s' % spacing_pixels)
    
    centers = [(x, x) for x in numpy.linspace(-1.2, +1.2, 9)]
    
    for x in numpy.linspace(-1.2, +1.2, 9):
        centers.append((-x, x))
    
    centers.append((0.5, 1.1))
    centers.append((1e-7, 1e-7))
    
    model_pol = model.polarisation_frame
    # Make the list of components
    rpix = model.wcs.wcs.crpix
    components = []
    for center in centers:
        ix, iy = center
        # The phase center in 0-relative coordinates is n // 2 so we centre the grid of
        # components on ny // 2, nx // 2. The wcs must be defined consistently.
        p = int(round(rpix[0] + ix * spacing_pixels * numpy.sign(model.wcs.wcs.cdelt[0]))), \
            int(round(rpix[1] + iy * spacing_pixels * numpy.sign(model.wcs.wcs.cdelt[1])))
        sc = pixel_to_skycoord(p[0], p[1], model.wcs, origin=1)
        log.info("Component at (%f, %f) [0-rel] %s" % (p[0], p[1], str(sc)))
        
        if ix != 0 and iy != 0:
            # Channel images
            comp = create_skycomponent(flux=flux, frequency=model.frequency, direction=sc,
                                       polarisation_frame=model_pol)
            components.append(comp)
    
    beam = create_low_test_beam(model)
    components = apply_beam_to_skycomponent(components, beam)
    
    return components


def create_unittest_model(vis, model_pol, npixel=None, cellsize=None, nchan=1):
    advice = advise_wide_field(vis, guard_band_image=2.0, delA=0.02, facets=1,
                               wprojection_planes=1, oversampling_synthesised_beam=4.0)
    if cellsize is None:
        cellsize = advice['cellsize']
    if npixel is None:
        npixel = advice['npixels2']
    model = create_image_from_visibility(vis, npixel=npixel, cellsize=cellsize, nchan=nchan,
                                         polarisation_frame=model_pol)
    return model


def insert_unittest_errors(vt, seed=180555):
    """Simulate gain errors and apply
    
    :param vt:
    :param phase_error:
    :param amplitude_error:
    :return:
    """
    numpy.random.seed(seed)
    controls = create_calibration_controls()
    amp_errors = {'T': 0.0, 'G': 0.01, 'B': 0.01}
    phase_errors = {'T': 1.0, 'G': 0.1, 'B': 0.01}
    for c in "TGB":
        gaintable = \
            create_gaintable_from_blockvisibility(vt, timeslice=controls[c]['timeslice'])
        gaintable = simulate_gaintable(gaintable,
                                       timeslice=controls[c]['timeslice'],
                                       phase_only=controls[c]['phase_only'],
                                       crosspol=controls[c]['shape'] == 'matrix',
                                       phase_error=phase_errors[c], amplitude_error=amp_errors[c])
        vt = apply_gaintable(vt, gaintable, inverse=True, timeslice=controls[c]['timeslice'])
    
    return vt
