# Tim Cornwell <realtimcornwell@gmail.com>
#
"""
Definition of structures needed by the function interface.
"""

import csv
import unittest

from astropy.coordinates import ICRS, EarthLocation
from astropy.wcs import WCS

from arl.data.data_models import *
from arl.data.parameters import arl_path
from arl.image.operations import import_image_from_fits, create_image_from_array, reproject_image
from arl.util.coordinate_support import *

log = logging.getLogger(__name__)


def create_configuration_from_file(antfile: str, name: str = None, location: EarthLocation = None, mount: str = 'altaz',
                                   names: str = "%d", frame: str = 'local',
                                   meta: dict = None,
                                   **kwargs):
    """ Define from a file

    :param names:
    :param antfile: Antenna file name
    :param name: Name of array e.g. 'LOWBD2'
    :param location:
    :param mount: mount type: 'altaz', 'xy'
    :param frame: 'local' | 'global'
    :param meta: Any meta info
    :returns: Configuration
    """
    antxyz = numpy.genfromtxt(antfile, delimiter=",")
    assert antxyz.shape[1] == 3, ("Antenna array has wrong shape %s" % antxyz.shape)
    nants = antxyz.shape[0]
    if frame == 'local':
        latitude = location.geodetic[1].to(u.rad).value
        antxyz = xyz_at_latitude(antxyz, latitude)
    anames = [names % ant for ant in range(nants)]
    mounts = numpy.repeat(mount, nants)
    fc = Configuration(location=location, names=anames, mount=mounts, xyz=antxyz, frame = frame)
    return fc


# noinspection PyUnresolvedReferences,PyUnresolvedReferences,PyUnresolvedReferences
def create_LOFAR_configuration(antfile: str, meta: dict = None,
                               **kwargs):
    """ Define from the LOFAR configuration file

    :param antfile:
    :param meta:
    :returns: Configuration
    """
    antxyz = numpy.genfromtxt(antfile, skip_header=2, usecols=[1, 2, 3], delimiter=",")
    nants = antxyz.shape[0]
    assert antxyz.shape[1] == 3, "Antenna array has wrong shape %s" % antxyz.shape
    anames = numpy.genfromtxt(antfile, dtype='str', skip_header=2, usecols=[0], delimiter=",")
    mounts = numpy.repeat('XY', nants)
    location = EarthLocation(x=[3826923.9] * u.m, y=[460915.1] * u.m, z=[5064643.2] * u.m)
    fc = Configuration(location=location, names=anames, mount=mounts, xyz=antxyz, frame = 'global')
    return fc


def create_named_configuration(name: str = 'LOWBD2', **kwargs):
    """ Standard configurations e.g. LOWBD2, MIDBD2

    :param name: name of Configuration LOWBD2, LOWBD1, LOFAR, VLAA
    :returns: Configuration
    """
    
    if name == 'LOWBD2':
        location = EarthLocation(lon="116.4999", lat="-26.7000", height=300.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/LOWBD2.csv"),
                                            location=location, mount='xy', names='LOWBD2_%d')
    elif name == 'LOWBD1':
        location = EarthLocation(lon="116.4999", lat="-26.7000", height=300.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/LOWBD1.csv"),
                                            location=location, mount='xy', names='LOWBD1_%d')
    elif name == 'LOWBD2-CORE':
        location = EarthLocation(lon="116.4999", lat="-26.7000", height=300.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/LOWBD2-CORE.csv"),
                                            location=location, mount='xy', names='LOWBD2_%d')
    elif name == 'LOFAR':
        fc = create_LOFAR_configuration(antfile=arl_path("data/configurations/LOFAR.csv"))
    elif name == 'VLAA':
        location = EarthLocation(lon="-107.6184", lat="34.0784", height=2124.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/VLA_A_hor_xyz.csv"),
                                            location=location,
                                            mount='altaz',
                                            names='VLA_%d')
    elif name == 'VLAA_north':
        location = EarthLocation(lon="-107.6184", lat="90.000", height=2124.0)
        fc = create_configuration_from_file(antfile=arl_path("data/configurations/VLA_A_hor_xyz.csv"),
                                            location=location,
                                            mount='altaz',
                                            names='VLA_%d')
    else:
        fc = Configuration()
        raise UserWarning("No such Configuration %s" % name)
    return fc



def create_test_image(canonical=True, npol=4, nchan=1, cellsize=None):
    """Create a useful test image

    This is the test image M31 widely used in ALMA and other simulations. It is actually part of an Halpha region in
    M31.

    :param cellsize:
    :param canonical: Make the image into a 4 dimensional image
    :param npol: Number of polarisations
    :param nchan: Number of channels
    :returns: Image
    """
    im = import_image_from_fits(arl_path("data/models/M31.MOD"))
    if canonical:
        im = replicate_image(im, nchan=nchan, npol=npol)
        if cellsize is not None:
            im.wcs.wcs.cdelt[0] = -180.0 * cellsize / numpy.pi
            im.wcs.wcs.cdelt[1] = +180.0 * cellsize / numpy.pi
        im.wcs.wcs.radesys = 'ICRS'
        im.wcs.wcs.equinox = 2000.00
    return im


# noinspection PyUnresolvedReferences,PyUnresolvedReferences,PyUnresolvedReferences,PyUnresolvedReferences,PyUnresolvedReferences,PyUnresolvedReferences
def create_low_test_image(npixel=16384, npol=1, nchan=1, cellsize=0.000015, frequency=1e8, channelwidth=1e6,
                          phasecentre=None):
    """Create LOW test image from S3
    
    The input catalog was generated at http://s-cubed.physics.ox.ac.uk/s3_sex using the following query
    Database: s3_sex
    SQL: select * from Galaxies where (pow(10,itot_151)*1000 > 1.0) and (right_ascension between -5 and 5) and (declination between -5 and 5);;
    Number of rows returned: 29966
    
    :param frequency:
    :param npixel: Number of pixels
    :param npol: Number of polarisations (all set to same value)
    :param nchan: Number of channels (all set to same value)
    :param cellsize: cellsize in radians
    :param channelwidth: Channel width (Hz)
    :param phasecentre: phasecentre (SkyCoord)
    :returns: Image
    """
    
    ras = []
    decs = []
    fluxes = []
    
    if phasecentre is None:
        phasecentre = SkyCoord(ra=+180.0 * u.deg, dec=-60.0 * u.deg, frame='icrs', equinox=2000.0)
    
    shape = [nchan, npol, npixel, npixel]
    w = WCS(naxis=4)
    # The negation in the longitude is needed by definition of RA, DEC
    w.wcs.cdelt = [-cellsize * 180.0 / numpy.pi, cellsize * 180.0 / numpy.pi, 1.0, channelwidth]
    w.wcs.crpix = [npixel // 2 + 1, npixel // 2 + 1, 1.0, 1.0]
    w.wcs.ctype = ["RA---SIN", "DEC--SIN", 'STOKES', 'FREQ']
    w.wcs.crval = [phasecentre.ra.value, phasecentre.dec.value, 1.0, frequency]
    w.naxis = 4
    
    w.wcs.radesys = 'ICRS'
    w.wcs.equinox = 2000.0
    
    model = create_image_from_array(numpy.zeros(shape), w)
    
    with open(arl_path('data/models/S3_151MHz_10deg.csv')) as csvfile:
        readCSV = csv.reader(csvfile, delimiter=',')
        r = 0
        for row in readCSV:
            # Skip first row
            if r > 0:
                ra = float(row[4]) + phasecentre.ra.deg
                dec = float(row[5]) + phasecentre.dec.deg
                alpha = (float(row[10])-float(row[9]))/numpy.log10(610.0/151.0)
                flux = numpy.power(10, float(row[9])) * numpy.power(frequency / 1.51e8, alpha)
                ras.append(ra)
                decs.append(dec)
                fluxes.append(flux)
            r += 1
    
    p = w.sub(2).wcs_world2pix(numpy.array(ras), numpy.array(decs), 0)
    total_flux = numpy.sum(fluxes)
    fluxes = numpy.array(fluxes)
    ip = numpy.round(p).astype('int')
    ok = numpy.where((0 <= ip[0,:]) & (npixel > ip[0,:]) & (0 <= ip[1,:]) & (npixel > ip[1,:]))[0]
    ps = ip[:,ok]
    actual_flux = numpy.sum(fluxes[ok])

    log.info('create_low_test_image: %d sources inside the image' % (ps.shape[1]))
    # noinspection PyStringFormat,PyStringFormat
    log.info('create_low_test_image: flux in S3 model = %.3f, actual flux in image = %.3f' % (total_flux, actual_flux))
    for chan in range(nchan):
        for pol in range(npol):
            model.data[chan, pol, ip[1,ok], ip[0,ok]] += fluxes[ok]
    
    return model


def create_low_test_beam(model):
    """Create a test power beam for LOW using an image from OSKAR
    
    This is in progress. Currently uses the wrong beam!
    
    :param model: Template image
    :returns: Image
    """
    
    beam = import_image_from_fits(arl_path('data/models/SKA1_LOW_beam.fits'))
    
    # Scale the image cellsize to account for the different in frequencies. Eventually we will want to
    # use a frequency cube
    log.info("create_low_test_beam: primary beam is defined at %.3f MHz" % (beam.wcs.wcs.crval[2]*1e-6))
    log.info("create_low_test_beam: scaling to model frequency %.3f MHz" % (model.wcs.wcs.crval[3]*1e-6))
    fscale = model.wcs.wcs.crval[3] / beam.wcs.wcs.crval[2]
    beam.wcs.wcs.crval[0] *= fscale
    beam.wcs.wcs.crval[1] *= fscale
    
    # Adjust for the different ordering of axes. When this includes a range of frequencies, we will need
    # to reshape the array as well
    beam.wcs.wcs.ctype[2], beam.wcs.wcs.ctype[3] = model.wcs.wcs.ctype[2], model.wcs.wcs.ctype[3]
    beam.wcs.wcs.cdelt[2], beam.wcs.wcs.cdelt[3] = model.wcs.wcs.cdelt[2], model.wcs.wcs.cdelt[2]
    beam.wcs.wcs.crval[2], beam.wcs.wcs.crval[3] = 1, model.wcs.wcs.crval[3]
    beam.wcs.wcs.cunit = model.wcs.wcs.cunit
    
    reprojected_beam, footprint = reproject_image(beam, model.wcs, shape=model.shape)
    reprojected_beam.data *= reprojected_beam.data
    
    return reprojected_beam


def replicate_image(im: Image, npol=4, nchan=1, frequency=1.4e9):
    """ Make a new canonical shape Image, extended along third and fourth axes by replication.

    The order of the data is [chan, pol, dec, ra]


    :param frequency:
    :param im:
    :param npol: Number of polarisation axes
    :param nchan: Number of spectral channels
    :returns: Image
    """
    
    if len(im.data.shape) == 2:
        fim = Image()
        
        newwcs = WCS(naxis=4)
        
        newwcs.wcs.crpix = [im.wcs.wcs.crpix[0], im.wcs.wcs.crpix[1], 1.0, 1.0]
        newwcs.wcs.cdelt = [im.wcs.wcs.cdelt[0], im.wcs.wcs.cdelt[1], 1.0, 1.0]
        newwcs.wcs.crval = [im.wcs.wcs.crval[0], im.wcs.wcs.crval[1], 1.0, frequency]
        newwcs.wcs.ctype = [im.wcs.wcs.ctype[0], im.wcs.wcs.ctype[1], 'STOKES', 'FREQ']
        
        fim.wcs = newwcs
        fshape = [nchan, npol, im.data.shape[1], im.data.shape[0]]
        fim.data = numpy.zeros(fshape)
        log.info("replicate_image: replicating shape %s to %s" % (im.data.shape, fim.data.shape))
        for i3 in range(nchan):
            for i2 in range(npol):
                fim.data[i3, i2, :, :] = im.data[:, :]
    else:
        fim = im
    
    return fim


def run_unittests(logLevel=logging.DEBUG, *args, **kwargs):
    """Runs the unit tests in all loaded modules.

    :param logLevel: The amount of logging to generate. By default, we
      show all log messages (level DEBUG)
    """
    
    # Set up logging environment
    rootLog = logging.getLogger()
    rootLog.setLevel(logLevel)
    rootLog.addHandler(logging.StreamHandler(sys.stderr))
    
    # Call unittest main
    unittest.main(*args, **kwargs)
    
if __name__ == '__main__':
    im=create_low_test_image()

