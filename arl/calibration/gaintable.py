# Tim Cornwell <realtimcornwell@gmail.com>
#
""" Visibility operations

"""

import copy

from arl.fourier_transforms.ftprocessor_params import *
from arl.util.coordinate_support import *
from arl.visibility.iterators import vis_timeslice_iter

log = logging.getLogger(__name__)


def gaintable_summary(gt):
    """Return string summarizing the Gaintable

    """
    return "%s rows, %.3f GB" % (gt.data.shape, gt.size())


def create_gaintable_from_blockvisibility(vis: BlockVisibility, time_width: float = None,
                                          frequency_width: float = None)  -> GainTable:
    """ Create gain table from visibility.
    
    This makes an empty gain table consistent with the BlockVisibility.
    
    :param vis: BlockVisibilty
    :param time_interval: Time interval between solutions (s)
    :param frequency_width: Frequency solution width (Hz)
    :returns: GainTable
    
    """
    assert type(vis) is BlockVisibility, "vis is not a BlockVisibility: %r" % vis
    
    nants = vis.nants
    utimes = numpy.unique(vis.time)
    ntimes = len(utimes)
    ufrequency = numpy.unique(vis.frequency)
    nfrequency = len(ufrequency)
    
    npol = vis.polarisation_frame.npol
    
    gainshape = [ntimes, nants, nfrequency, npol]
    gain = numpy.ones(gainshape, dtype='complex')
    gain_weight = numpy.ones(gainshape)
    gain_time = utimes
    gain_frequency = ufrequency
    gain_residual = numpy.zeros([ntimes, nfrequency, npol])
    
    gt = GainTable(gain=gain, time=gain_time, weight=gain_weight, residual=gain_residual, frequency=gain_frequency,
                   receptor_frame=vis.polarisation_frame)

    assert type(gt) is GainTable, "gt is not a GainTable: %r" % gt

    return gt


def apply_gaintable(vis: BlockVisibility, gt: GainTable, inverse=False) -> BlockVisibility:
    """Apply a gain table to a block visibility
    
    The corrected visibility is::
    
        V_corrected = {g_i * g_j^*}^-1 V_obs
        
    If the visibility data are polarised e.g. polarisation_frame("linear") then the inverse operator
    represents an actual inverse of the gains.
    
    :param vis: Visibility to have gains applied
    :param gt: Gaintable to be applied
    :param inverse: Apply the inverse (default=False)
    :returns: input vis with gains applied
    
    """
    assert type(vis) is BlockVisibility, "vis is not a BlockVisibility: %r" % vis
    assert type(gt) is GainTable, "gt is not a GainTable: %r" % gt

    if inverse:
        log.info('apply_gaintable: Apply inverse gaintable')
    else:
        log.info('apply_gaintable: Apply gaintable')
    
    for chunk, rows in enumerate(vis_timeslice_iter(vis)):
        vistime = numpy.average(vis.time[rows])
        integration_time = numpy.average(vis.integration_time[rows])
        gaintable_rows = abs(gt.time - vistime) < integration_time / 2.0
        
        # Lookup the gain for this set of visibilities
        gain = gt.data['gain'][gaintable_rows]
        gwt = gt.data['weight'][gaintable_rows]
        if inverse:  # TODO: Make this true inverse for polarisation
            gain[gwt > 0.0] = 1.0 / gain[gwt > 0.0]
        
        original = vis.vis[rows]
        applied = copy.deepcopy(original)
        for a1 in range(vis.nants - 1):
            for a2 in range(a1 + 1, vis.nants):
                applied[:, a2, a1, :, :] = gain[:, a1, :, :] * numpy.conjugate(gain[:, a2, :, :]) * \
                                           original[:, a2, a1, :, :]
        
        vis.data['vis'][rows] = applied
    return vis


def solve_gaintable(vis: BlockVisibility, modelvis: BlockVisibility, phase_only=True, niter=30, tol=1e-8) -> GainTable:
    """Solve a gain table to a block visibility
    
    :param vis: BlockVisibility containing the observed data
    :param modelvis: BlockVisibility containing the visibility predicted by a model
    :param phase_only: Solve only for the phases (default=True)
    :param niter: Number of iterations (default 30)
    :param tol: Iteration stops when the fractional change in the gain solution is below this tolerance
    :returns: GainTable containing solution
    
    """
    assert type(vis) is BlockVisibility, "vis is not a BlockVisibility: %r" % vis
    assert type(modelvis) is BlockVisibility, "modelvis is not a BlockVisibility: %r" % vis

    if phase_only:
        log.info('solve_gaintable: Solving for phase only')
    else:
        log.info('solve_gaintable: Solving for complex gain')
    
    gt = create_gaintable_from_blockvisibility(vis)
    
    for chunk, rows in enumerate(vis_timeslice_iter(vis)):
        
        # Form the point source equivalent visibility
        X = numpy.zeros_like(vis.vis[rows])
        Xwt = numpy.abs(modelvis.vis[rows]) ** 2 * modelvis.weight[rows]
        mask = Xwt > 0.0
        X[mask] = vis.vis[rows][mask] / modelvis.vis[rows][mask]
        
        # Now average over time, chan. The axes of X are time, antenna2, antenna1, chan, pol
        
        Xave = numpy.average(X * Xwt, axis=(0))
        XwtAve = numpy.average(Xwt, axis=(0))
        
        mask = XwtAve > 0.0
        Xave[mask] = Xave[mask] / XwtAve[mask]
        
        gt.data['gain'][chunk, ...], gt.data['weight'][chunk, ...], gt.data['residual'][chunk, ...] = \
            solve_antenna_gains_itsubs(Xave, XwtAve, phase_only=phase_only, niter=niter, tol=tol)

    assert type(gt) is GainTable, "gt is not a GainTable: %r" % gt

    return gt


def solve_antenna_gains_itsubs(X, Xwt, niter=30, tol=1e-8, phase_only=True, refant=0):
    """Solve for the antenna gains
    
    X(antenna2, antenna1) = gain(antenna1) conj(gain(antenna2))
    
    This uses an iterative substitution algorithm due to Larry D'Addario c 1980'ish. Used
    in the original VLA Dec-10 Antsol.
    
    :param X: Equivalent point source visibility[nants, nants, ...]
    :param Xwt: Equivalent point source weight [nants, nants, ...]
    :param niter: Number of iterations
    :param tol: tolerance on solution change
    :returns: gain [nants, ...], weight [nants, ...]
    """
    
    nants = X.shape[0]
    for ant1 in range(nants):
        X[ant1, ant1, ...] = 0.0
        Xwt[ant1, ant1, ...] = 0.0
        for ant2 in range(ant1 + 1, nants):
            X[ant1, ant2, ...] = numpy.conjugate(X[ant2, ant1, ...])
            Xwt[ant1, ant2, ...] = Xwt[ant2, ant1, ...]
    
    def gain_substitution(gain, X, Xwt):
        
        nants = gain.shape[0]
        g = numpy.ones_like(gain, dtype='complex')
        gwt = numpy.zeros_like(gain, dtype='float')
        
        for ant1 in range(nants):
            top = numpy.sum(gain[:, ...] * X[:, ant1, ...] * Xwt[:, ant1, ...], axis=0)
            bot = numpy.sum((gain[:, ...] * numpy.conjugate(gain[:, ...])).real * Xwt[:, ant1, ...], axis=0)
            g[ant1, ...] = top / bot
            gwt[ant1, ...] = bot
        return g, gwt
    
    
    gainshape = X.shape[1:]
    gain = numpy.ones(shape=gainshape, dtype=X.dtype)
    gwt = numpy.zeros(shape=gainshape, dtype=Xwt.dtype)
    for iter in range(niter):
        gainLast = gain
        gain, gwt = gain_substitution(gain, X, Xwt)
        if phase_only:
            gain = gain / numpy.abs(gain)
        gain *= numpy.conjugate(gain[refant, ...]) / numpy.abs(gain[refant, ...])
        gain = 0.5 * (gain + gainLast)
        change = numpy.max(numpy.abs(gain - gainLast))
        if change < tol:
            return gain, gwt, solution_residual(gain, X, Xwt)

    return gain, gwt, solution_residual(gain, X, Xwt)

def solution_residual(gain, X, Xwt):
    """Calculate residual across all baselines of gain for point source equivalent visibilities
    
    :param gain: gain [nant, ...]
    :param X: Point source equivalent visibility [nant, ...]
    :param Xwt: Point source equivalent weight [nant, ...]
    :returns: residual[...]
    """

    nants = gain.shape[0]

    residual = 0.0
    sumwt = 0.0

    for ant1 in range(nants):
        sumwt += numpy.sum(Xwt[:, ant1, ...], axis=0)
        residual += numpy.sum(numpy.abs(X[:, ant1, ...] - gain[ant1, ...] * numpy.conjugate(gain[:, ...])) ** 2 \
                              * Xwt[:, ant1, ...], axis=0)
    residual = numpy.sqrt(residual / sumwt)
    return residual