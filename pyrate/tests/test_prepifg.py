"""
Tests for prepifg.py: resampling, subsetting etc.

.. codeauthor:: Ben Davies, Sudipta Basak
"""

import os, sys, unittest
from os.path import exists, join

from math import floor
import numpy as np
from scipy.stats.stats import nanmean
from numpy import isnan, nanmax, nanmin
from numpy import ones, nan, reshape, sum as npsum
from numpy.testing import assert_array_almost_equal, assert_array_equal

from pyrate import config as cfg
from pyrate.shared import Ifg, DEM
from pyrate.prepifg import CUSTOM_CROP, MAXIMUM_CROP, MINIMUM_CROP, ALREADY_SAME_SIZE
from pyrate.prepifg import prepare_ifgs, resample, PreprocessError, CustomExts
from pyrate.prepifg import mlooked_path, extents_from_params
from pyrate.tests.common import SYD_TEST_MATLAB_PREPIFG_DIR
from pyrate.tests.common import PREP_TEST_TIF, SYD_TEST_DEM_DIR
from pyrate.tests.common import SYD_TEST_DEM_TIF

from osgeo import gdal
gdal.UseExceptions()

if not exists(PREP_TEST_TIF):
    sys.exit("ERROR: Missing 'prepifg' dir for unittests\n")


# convenience ifg creation funcs
def diff_exts_ifgs():
    """Returns pair of test Ifgs with different extents"""
    bases = ['geo_060619-061002.tif', 'geo_070326-070917.tif']
    return [Ifg(join(PREP_TEST_TIF, p)) for p in bases]


def same_exts_ifgs():
    """Return pair of Ifgs with same extents"""
    return [Ifg(join(PREP_TEST_TIF, f)) for f in ('0.tif', '1.tif')]


def test_extents_from_params():
    xf, yf = 1.0, 2.0
    xl, yl = 5.0, 7.0
    pars = {cfg.IFG_XFIRST: xf, cfg.IFG_XLAST: xl,
            cfg.IFG_YFIRST: yf, cfg.IFG_YLAST: yl}

    assert extents_from_params(pars) == CustomExts(xf, yf, xl, yl)


class PrepifgOutputTests(unittest.TestCase):
    """Tests aspects of the prepifg.py script, such as resampling."""

    def __init__(self, *args, **kwargs):
        super(PrepifgOutputTests, self).__init__(*args, **kwargs)

    @staticmethod
    def assert_geotransform_equal(files):
        """
        Asserts geotransforms for the given files are equivalent. Files can be paths
        to datasets, or GDAL dataset objects.
        """
        assert len(files) > 1, "Need more than 1 file to compare"
        if not all([hasattr(f, "GetGeoTransform") for f in files]):
            datasets = [gdal.Open(f) for f in files]
            assert all(datasets)
        else:
            datasets = files

        transforms = [ds.GetGeoTransform() for ds in datasets]
        head = transforms[0]
        for t in transforms[1:]:
            assert t == head, "Extents do not match!"

    def setUp(self):
        self.xs = 0.000833333
        self.ys = -self.xs

        # FIXME: dump output to tmp dir?
        self.ifgs = diff_exts_ifgs()
        paths = ["geo_060619-061002_1rlks_1cr.tif",
                 "geo_060619-061002_1rlks_2cr.tif",
                 "geo_060619-061002_1rlks_3cr.tif",
                 "geo_060619-061002_4rlks_3cr.tif",
                 "geo_070326-070917_1rlks_1cr.tif",
                 "geo_070326-070917_1rlks_2cr.tif",
                 "geo_070326-070917_1rlks_3cr.tif",
                 "geo_070326-070917_4rlks_3cr.tif"]
        self.exp_files = [join(PREP_TEST_TIF, p) for p in paths]

    def test_mlooked_paths(self):
        test_mlooked_path()

    def test_extents_from_params(self):
        test_extents_from_params()

    def tearDown(self):
        for f in self.exp_files:
            if exists(f):
                os.remove(f)

    def _custom_ext_latlons(self):
        return [150.91 + (7 * self.xs),  # xfirst
                -34.17 + (16 * self.ys),  # yfirst
                150.91 + (27 * self.xs),  # 20 cells from xfirst
                -34.17 + (44 * self.ys)]  # 28 cells from yfirst

    def _custom_extents_tuple(self):
        return CustomExts(*self._custom_ext_latlons())

    def test_default_max_extents(self):
        """Test ifgcropopt=2 crops datasets to max bounding box extents."""
        xlooks = ylooks = 1
        prepare_ifgs(self.ifgs, MAXIMUM_CROP, xlooks, ylooks)
        for f in [self.exp_files[1], self.exp_files[5]]:
            self.assertTrue(exists(f), msg="Output files not created")

        # output files should have same extents
        # NB: also verifies gdalwarp correctly copies geotransform across
        ifg = Ifg(self.exp_files[1])
        ifg.open()
        gt = ifg.dataset.GetGeoTransform()

        # copied from gdalinfo output
        exp_gt = (150.91, 0.000833333, 0, -34.17, 0, -0.000833333)
        for i, j in zip(gt, exp_gt):
            self.assertAlmostEqual(i, j)
        self.assert_geotransform_equal([self.exp_files[1], self.exp_files[5]])

    def test_min_extents(self):
        """Test ifgcropopt=1 crops datasets to min extents."""
        xlooks = ylooks = 1
        prepare_ifgs(self.ifgs, MINIMUM_CROP, xlooks, ylooks)
        ifg = Ifg(self.exp_files[0])
        ifg.open()

        # output files should have same extents
        # NB: also verifies gdalwarp correctly copies geotransform across
        # NB: expected data copied from gdalinfo output
        gt = ifg.dataset.GetGeoTransform()
        exp_gt = (150.911666666, 0.000833333, 0, -34.172499999, 0, -0.000833333)
        for i, j in zip(gt, exp_gt):
            self.assertAlmostEqual(i, j)
        self.assert_geotransform_equal([self.exp_files[0], self.exp_files[4]])

    def test_custom_extents(self):
        xlooks = ylooks = 1
        cext = self._custom_extents_tuple()
        prepare_ifgs(self.ifgs, CUSTOM_CROP, xlooks, ylooks, user_exts=cext)

        ifg = Ifg(self.exp_files[2])
        ifg.open()

        gt = ifg.dataset.GetGeoTransform()
        exp_gt = (cext.xfirst, self.xs, 0, cext.yfirst, 0, self.ys)

        for i, j in zip(gt, exp_gt):
            self.assertAlmostEqual(i, j)
        self.assert_geotransform_equal([self.exp_files[2], self.exp_files[6]])

    def test_custom_extents_misalignment(self):
        """Test misaligned cropping extents raise errors."""
        xlooks = ylooks = 1
        latlons = tuple(self._custom_ext_latlons())
        for i, _ in enumerate(['xfirst', 'yfirst', 'xlast', 'ylast']):
            #error = step / pi * [1000 100]
            for error in [0.265258, 0.026526]:
                tmp_latlon = list(latlons)
                tmp_latlon[i] += error
                cext = CustomExts(*tmp_latlon)

                self.assertRaises(PreprocessError, prepare_ifgs, self.ifgs,
                                CUSTOM_CROP, xlooks, ylooks, user_exts=cext)

    def test_nodata(self):
        """Verify NODATA value copied correctly (amplitude band not copied)"""
        xlooks = ylooks = 1
        prepare_ifgs(self.ifgs, MINIMUM_CROP, xlooks, ylooks)

        for ex in [self.exp_files[0], self.exp_files[4]]:
            ifg = Ifg(ex)
            ifg.open()
            # NB: amplitude band doesn't have a NODATA value
            self.assertTrue(isnan(ifg.dataset.GetRasterBand(1).GetNoDataValue()))

    def test_nans(self):
        """Verify NaNs replace 0 in the multilooked phase band"""
        xlooks = ylooks = 1
        prepare_ifgs(self.ifgs, MINIMUM_CROP, xlooks, ylooks)

        for ex in [self.exp_files[0], self.exp_files[4]]:
            ifg = Ifg(ex)
            ifg.open()

            phase = ifg.phase_band.ReadAsArray()
            self.assertFalse((phase == 0).any())
            self.assertTrue((isnan(phase)).any())

        self.assertAlmostEqual(nanmax(phase), 4.247, 3)  # copied from gdalinfo
        self.assertAlmostEqual(nanmin(phase), 0.009, 3)  # copied from gdalinfo

    def test_multilook(self):
        """Test resampling method using a scaling factor of 4"""
        scale = 4  # assumes square cells
        self.ifgs.append(DEM(SYD_TEST_DEM_TIF))
        cext = self._custom_extents_tuple()
        xlooks = ylooks = scale
        prepare_ifgs(self.ifgs, CUSTOM_CROP, xlooks, ylooks,
                     thresh=1.0, user_exts=cext)

        for n, ipath in enumerate([self.exp_files[3], self.exp_files[7]]):
            i = Ifg(ipath)
            i.open()
            self.assertEqual(i.dataset.RasterXSize, 20 / scale)
            self.assertEqual(i.dataset.RasterYSize, 28 / scale)

            # verify resampling
            path = join(PREP_TEST_TIF, "%s.tif" % n)
            ds = gdal.Open(path)
            src_data = ds.GetRasterBand(2).ReadAsArray()
            exp_resample = multilooking(src_data, scale, scale, thresh=0)
            self.assertEqual(exp_resample.shape, (7, 5))
            assert_array_almost_equal(exp_resample, i.phase_band.ReadAsArray())
            # os.remove(ipath)

        # verify DEM has been correctly processed
        # ignore output values as resampling has already been tested for phase
        exp_dem_path = join(SYD_TEST_DEM_DIR, 'sydney_trimmed_4rlks_3cr.tif')
        self.assertTrue(exists(exp_dem_path))

        dem = DEM(exp_dem_path)
        dem.open()
        self.assertEqual(dem.dataset.RasterXSize, 20 / scale)
        self.assertEqual(dem.dataset.RasterYSize, 28 / scale)
        data = dem.height_band.ReadAsArray()
        self.assertTrue(data.ptp() != 0)

    def test_invalid_looks(self):
        """Verify only numeric values can be given for multilooking"""
        values = [0, -1, -10, -100000.6, ""]
        for v in values:
            self.assertRaises(PreprocessError, prepare_ifgs, self.ifgs,
                                CUSTOM_CROP, xlooks=v, ylooks=1)

            self.assertRaises(PreprocessError, prepare_ifgs, self.ifgs,
                                CUSTOM_CROP, xlooks=1, ylooks=v)


class ThresholdTests(unittest.TestCase):
    """Tests for threshold of data -> NaN during resampling."""

    def test_nan_threshold_inputs(self):
        data = ones((1,1))
        for thresh in [-10, -1, -0.5, 1.000001, 10]:
            self.assertRaises(ValueError, resample, data, 2, 2, thresh)

    def test_nan_threshold(self):
        # test threshold based on number of NaNs per averaging tile
        data = ones((2, 10))
        data[0, 3:] = nan
        data[1, 7:] = nan

        # key: NaN threshold as a % of pixels, expected result
        expected = [(0.0, [1, nan, nan, nan, nan]),
                    (0.25, [1, nan, nan, nan, nan]),
                    (0.5, [1, 1, nan, nan, nan]),
                    (0.75, [1, 1, 1, nan, nan]),
                    (1.0, [1, 1, 1, 1, nan])]

        for thresh, exp in expected:
            res = resample(data, xscale=2, yscale=2, thresh=thresh)
            assert_array_equal(res, reshape(exp, res.shape))

    def test_nan_threshold_alt(self):
        # test threshold on odd numbers
        data = ones((3, 6))
        data[0] = nan
        data[1, 2:5] = nan

        expected = [(0.4, [nan, nan]), (0.5, [1, nan]), (0.7, [1, 1])]
        for thresh, exp in expected:
            res = resample(data, xscale=3, yscale=3, thresh=thresh)
            assert_array_equal(res, reshape(exp, res.shape))


class SameSizeTests(unittest.TestCase):
    """Tests aspects of the prepifg.py script, such as resampling."""

    def __init__(self, *args, **kwargs):
        super(SameSizeTests, self).__init__(*args, **kwargs)
        self.xs = 0.000833333
        self.ys = -self.xs

    # TODO: check output files for same extents?
    # TODO: make prepifg dir readonly to test output to temp dir
    # TODO: move to class for testing same size option?
    def test_already_same_size(self):
        # should do nothing as layers are same size & no multilooking required
        res = prepare_ifgs(same_exts_ifgs(), ALREADY_SAME_SIZE, 1, 1)
        self.assertFalse(any(res))

    def test_already_same_size_mismatch(self):
        self.assertRaises(PreprocessError, prepare_ifgs,
                        diff_exts_ifgs(), ALREADY_SAME_SIZE, 1, 1)

    # TODO: ensure multilooked files written to output dir
    def test_same_size_multilooking(self):
        ifgs = same_exts_ifgs()
        xlooks = ylooks = 2

        mlooked = prepare_ifgs(ifgs, ALREADY_SAME_SIZE, xlooks, ylooks)
        self.assertEqual(len(mlooked), 2)

        for ifg in mlooked:
            self.assertEqual(ifg.x_step, xlooks * self.xs)
            self.assertEqual(ifg.x_step, ylooks * self.xs)
            # os.remove(ifg.data_path)


def test_mlooked_path():
    path = 'geo_060619-061002.tif'
    assert mlooked_path(path, looks=2, crop_out=4) == \
           'geo_060619-061002_2rlks_4cr.tif'

    path = 'some/dir/geo_060619-061002.tif'
    assert mlooked_path(path, looks=4, crop_out=2) == \
           'some/dir/geo_060619-061002_4rlks_2cr.tif'

    path = 'some/dir/geo_060619-061002_4rlks.tif'
    assert mlooked_path(path, looks=4, crop_out=8) == \
           'some/dir/geo_060619-061002_4rlks_4rlks_8cr.tif'


#class LineOfSightTests(unittest.TestCase):
    #def test_los_conversion(self):
        # TODO: needs LOS matrix
        # TODO: this needs to work from config and incidence files on disk
        # TODO: is convflag (see 'ifgconv' setting) used or just defaulted?
        # TODO: los conversion has 4 options: 1: ignore, 2: vertical, 3: N/S, 4: E/W
        # also have a 5th option of arbitrary azimuth angle (Pirate doesn't have this)
    #    params = _default_extents_param()
    #    params[IFG_CROP_OPT] = MINIMUM_CROP
    #    params[PROJECTION_FLAG] = None
    #    prepare_ifgs(params)


    #def test_phase_conversion(self):
        # TODO: check output data is converted to mm from radians (in prepifg??)
        #raise NotImplementedError


class LocalMultilookTests(unittest.TestCase):
    """Tests for local testing functions"""

    def test_multilooking_thresh(self):
        data = ones((3, 6))
        data[0] = nan
        data[1, 2:5] = nan
        expected = [(6, [nan, nan]),
                    (5, [1, nan]),
                    (4, [1, 1])]
        scale = 3
        for thresh, exp in expected:
            res = multilooking(data, scale, scale, thresh)
            assert_array_equal(res, reshape(exp, res.shape))


def multilooking(src, xscale, yscale, thresh=0):
    """
    Port of looks.m from MATLAB Pirate.

    src: numpy array of phase data
    thresh: min number of non-NaNs required for a valid tile resampling
    """
    thresh = int(thresh)
    num_cells = xscale * yscale
    if thresh > num_cells or thresh < 0:
        msg = "Invalid threshold: %s (need 0 <= thr <= %s" % (thresh, num_cells)
        raise ValueError(msg)

    rows, cols = src.shape
    rows_lowres = int(floor(rows / yscale))
    cols_lowres = int(floor(cols / xscale))
    dest = ones((rows_lowres, cols_lowres)) * nan

    size = xscale * yscale
    for r in range(rows_lowres):
        for c in range(cols_lowres):
            ys = r * yscale
            ye = ys + yscale
            xs = c * xscale
            xe = xs + xscale

            patch = src[ys:ye, xs:xe]
            num_values = num_cells - npsum(isnan(patch))

            if num_values >= thresh and num_values > 0:
                reshaped = patch.reshape(size)  # nanmean() only works on 1 axis
                dest[r, c] = nanmean(reshaped)

    return dest


class MatlabEqualityTest(unittest.TestCase):
    """
    Matlab to python prepifg equality test
    """

    def setUp(self):
        from pyrate.tests.common import sydney5_ifgs
        self.ifgs = sydney5_ifgs()
        self.ifgs_with_nan = prepare_ifgs(self.ifgs,
                                          crop_opt=1, xlooks=1, ylooks=1)

    def tearDown(self):
        from pyrate.prepifg import mlooked_path
        for i in self.ifgs:
            if os.path.exists(i.data_path):
                os.remove(mlooked_path(i.data_path, looks=1, crop_out=1))

    def test_matlab_prepifg_equality_array(self):
        """
        Matlab to python prepifg equality test
        """
        # path to csv folders from matlab output
        from pyrate.tests.common import SYD_TEST_MATLAB_PREPIFG_DIR

        onlyfiles = [f for f in os.listdir(SYD_TEST_MATLAB_PREPIFG_DIR)
                if os.path.isfile(os.path.join(SYD_TEST_MATLAB_PREPIFG_DIR, f))
                and f.endswith('.csv') and f.__contains__('_rad_')]

        for i, f in enumerate(onlyfiles):
            ifg_data = np.genfromtxt(os.path.join(
                SYD_TEST_MATLAB_PREPIFG_DIR, f), delimiter=',')
            for k, j in enumerate(self.ifgs):
                if f.split('_rad_')[-1].split('.')[0] == \
                        os.path.split(j.data_path)[-1].split('.')[0]:
                    np.testing.assert_array_almost_equal(ifg_data,
                        self.ifgs_with_nan[k].phase_data, decimal=2)

    def test_matlab_prepifg_and_convert_wavelength(self):
        """
        Matlab to python prepifg equality test
        """
        # path to csv folders from matlab output
        for i in self.ifgs_with_nan:
            if not i.mm_converted:
                i.convert_to_mm()
        onlyfiles = [f for f in os.listdir(SYD_TEST_MATLAB_PREPIFG_DIR)
                if os.path.isfile(os.path.join(SYD_TEST_MATLAB_PREPIFG_DIR, f))
                and f.endswith('.csv') and f.__contains__('_mm_')]

        count = 0
        for i, f in enumerate(onlyfiles):
            ifg_data = np.genfromtxt(os.path.join(
                SYD_TEST_MATLAB_PREPIFG_DIR, f), delimiter=',')
            for k, j in enumerate(self.ifgs):
                if f.split('_mm_')[-1].split('.')[0] == \
                        os.path.split(j.data_path)[-1].split('.')[0]:
                    count += 1
                    # all numbers equal
                    np.testing.assert_array_almost_equal(ifg_data,
                        self.ifgs_with_nan[k].phase_data, decimal=2)

                    # means must also be equal
                    self.assertAlmostEqual(np.nanmean(ifg_data),
                        np.nanmean(self.ifgs_with_nan[k].phase_data), places=4)

                    # number of nans must equal
                    self.assertEqual(np.sum(np.isnan(ifg_data)),
                        np.sum(np.isnan(self.ifgs_with_nan[k].phase_data)))

        # ensure we have the correct number of matches
        self.assertEqual(count, len(self.ifgs))

if __name__ == "__main__":
    unittest.main()