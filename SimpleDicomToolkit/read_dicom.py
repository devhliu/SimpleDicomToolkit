"""
Created on Tue Sep  5 16:54:20 2017

@author: HeyDude
"""
import os

import SimpleDicomToolkit
import datetime
import SimpleITK as sitk




# source: http://dicom.nema.org/dicom/2013/output/chtml/part05/sect_6.2.html
VR_STRING   = ('AE', 'AS', 'AT', 'CS', 'LO', 'LT', 'OB', 'OW', \
                   'SH', 'ST', 'UI', 'UN', 'UT') # stored as string
VR_PN       = 'PN'
VR_DATE     = 'DA'
VR_DATETIME = 'DT'
VR_TIME     = 'TM'
VR_FLOAT    = ('DS', 'FL', 'FD', 'OD') #DS is unparsed, FL and FD are floats
VR_INT      = ('IS', 'SL', 'SS', 'UL', 'US')
VR_SEQ      = 'SQ'

class DicomReadable():
    """ Superclass for DicomFiles and DicomDatabaseSQL """
    _images = None
    _image = None
    MAX_FILES = 5000 # max number of files to be read at by property images
    SUV = True # convert PET images to SUV

    @property
    def files(self):
        """ List of dicom files that will be read to an image or images. """
        # must be implemented by subclass
        raise NotImplementedError

    @property
    def series_count(self):
        """ Return the number of dicom series present"""
        if not hasattr(self, 'SeriesInstanceUID'):
            return 0

        uids = getattr(self, 'SeriesInstanceUID')

        if isinstance(uids, str):
            return 1
        elif isinstance(uids, list):
            return len(uids)
        else:
            raise ValueError

    @property
    def image(self):
        """ Returns an sitk image for the files in the files property.
            All files must belong to the same dicom series
            (same SeriesInstanceUID). """

        assert self.series_count == 1
        if self._image is None:
            try:
                self._image = read_serie(self, SUV=self.SUV)
            except:
                print('Error during reading image serie')
                raise

        return self._image

    @property
    def images(self):
        """ Returns a dictionary with keys the SeriesInstanceUID and
            values the sitkimage belonging tot the set of files belonging to
            the same dicom series (same SeriesInstanceUID). Number of files
            in the files property cannot exceed the MAX_FILES property.
            This prevents reading of too large data sets """

        if len(self.files) > self.MAX_FILES:
            print('Number of files exceeds MAX_FILES property')
            raise IOError

        if self._images is None:
            assert hasattr(self, SimpleDicomToolkit.SERIESINSTANCEUID)
            try:
                self._images = read_series(self, SUV=self.SUV)
            except:
                print('Error during reading image series')
                raise

        return self._images

    @staticmethod
    def files_in_folder(dicom_dir, recursive=False):
        """ Find all files in a folder, use recursive if files inside subdirs
        should be included. """

        # Walk through a folder and recursively list all files
        if not recursive:
            files = os.listdir(dicom_dir)
        else:
            files = []
            for root, dirs, filenames in os.walk(dicom_dir):
                for file in filenames:
                    full_file = os.path.join(root, file)
                    if os.path.isfile(full_file):
                        files += [full_file]
            # remove system specific files and the database file that
            # start with '.'
            files = [f for f in files if not os.path.split(f)[1][0] == '.']

        return files


def read_files(file_list):
    """ Read a file or list of files using SimpleTIK. A file list will be
         read as an image series in SimpleITK. """
    if isinstance(file_list, str):
        file_reader = sitk.ImageFileReader()
        file_reader.SetFileName(file_list)

    elif isinstance(file_list, (tuple, list)):
        file_reader = sitk.ImageSeriesReader()
        file_reader.SetFileNames(file_list)

    try:
        image = file_reader.Execute()
    except:
        print('cannot read file: {0}'.format(file_list))
        raise IOError

    return image


def read_series(dicom_files, series_uids=None,
                flatten=True, rescale=True, SUV=False):
    """ Read an entire dicom database to SimpleITK images. A dictionary is
        returned with SeriesInstanceUID as key and SimpleITK images as values.

        series_uids: When None (default) all series are read. Otherwise a
                    single SeriesInstanceUID may be specified or a list of UIDs

        split_acquisitions: Returns seperate images for each acquisition number.
        single_output: Return a single image and header if only one dicom series
                       was found. Same output as read_serie.
        """


    if series_uids is None: # read everyting
        series_uids = dicom_files.SeriesInstanceUID

    if not isinstance(series_uids, (tuple, list)):
        series_uids = [series_uids]

    dicom_filess = [dicom_files.filter(SimpleDicomToolkit.SERIESINSTANCEUID, uid) \
                    for uid in series_uids]

    reader = lambda df: read_serie(df, SUV=SUV, rescale=rescale)
    result = [reader(df) for df in dicom_filess]

    images, headers = list(zip(*result))

    if len(images) == 1 and flatten:
        images = images[0]
        headers = headers[0]

    return images

def read_serie(dicom_files, rescale=True, SUV=False):
    """ Read a single image serie from a dicom database to SimpleITK images.

        series_uid: Define the SeriesInstanceUID to be read from the database.
                    When None (default) it is assumed that the database
                    contains a single image series (otherwise an error
                    is raised).

        split_acquisitions: Returns seperate images for each acquisition number.
        """


    assert dicom_files.series_count == 1 # multiple series should be read by read_series

    try: # sort slices may heavily depend on the exact dicom structure from the vendor.
        # Siemens PET and CT have a slice location property
        dicom_files = dicom_files.sort('SliceLocation')
    except:
        print('Slice Sorting Failed')
        raise

    files = dicom_files.files
    if hasattr(dicom_files, 'folder'):
        files = [os.path.join(dicom_files.folder, file) for file in files]

    image = read_files(files)

#    if rescale:
#        print('Rescaling image')
#        slope, intercept = rescale_values(dicom_files)
#        image *= slope
#        image += intercept


    # calculate and add a SUV scaling factor for PET.
    if dicom_files.SOPClassUID == SimpleDicomToolkit.SOP_CLASS_UID_PET:
        try:
            factor = suv_scale_factor(dicom_files)

        except:
            print('No SUV factor could be calculated!')
            factor = 1

        if SUV:
            image *= factor

        setattr(dicom_files, SimpleDicomToolkit.SUV_SCALE_FACTOR, factor)

    return image

def suv_scale_factor(header):
    """ Calculate the SUV scaling factor (Bq/cc --> SUV) based on information
    in the header. Works on Siemens PET Dicom Headers. """

    # header = image.header
    # calc suv scaling

    nuclide_info   = header.RadiopharmaceuticalInformationSequence[0]
    nuclide_dose   = float(nuclide_info.RadionuclideTotalDose)
    series_date    = header.SeriesDate.date()
    series_time    = header.SeriesTime.time()
    injection_time = nuclide_info.RadiopharmaceuticalStartTime.time()

    series_dt      = datetime.datetime.combine(series_date, series_time)
    injection_dt   = datetime.datetime.combine(series_date, injection_time)


    half_life      = float(nuclide_info.RadionuclideHalfLife)

    patient_weight = float(header.PatientWeight)


    # injection_time = dateutil.parser.parse(injection_time)
    # series_time = dateutil.parser.parse(series_time)

    delta_time = (series_dt - injection_dt).total_seconds()

    decay_correction = 0.5 ** (delta_time / half_life)

    suv_scaling = (patient_weight * 1000) / (decay_correction * nuclide_dose)

    return suv_scaling


def rescale_values(header=None):
    """ Return rescale slope and intercept if they are in the dicom headers,
    otherwise 1 is returned for slope and 0 for intercept. """
    # apply rescale slope and intercept to the image

    if hasattr(header, SimpleDicomToolkit.REALWORLDVALUEMAPPINGSEQUENCE):
        slope = header.RealWorldValueMappingSequence[0].RealWorldValueSlope
    elif hasattr(header, SimpleDicomToolkit.RESCALESLOPE):
        slope = header.RescaleSlope
    else:
        print('No rescale slope found in dicom header')
        slope = 1

    if hasattr(header, SimpleDicomToolkit.REALWORLDVALUEMAPPINGSEQUENCE):
        intercept = header.RealWorldValueMappingSequence[0].RealWorldValueIntercept
    elif hasattr(header, SimpleDicomToolkit.RESCALEINTERCEPT):
        intercept = header.RescaleIntercept
    else:
        print('No rescale slope found in dicom header')
        intercept = 1

    print(slope, intercept)
    return slope, intercept
