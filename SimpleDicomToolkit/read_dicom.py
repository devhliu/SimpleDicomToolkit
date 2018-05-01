"""
Created on Tue Sep  5 16:54:20 2017

@author: HeyDude
"""
import os

import SimpleDicomToolkit
import datetime
import SimpleITK as sitk
import dateutil
import pydicom
from dicom_parser import Parser

class DicomReadable():
    """ Superclass for DicomFiles and DicomDatabaseSQL """
    _images = None
    _image = None
    _headers = None
    MAX_FILES = 5000 # max number of files to be read at by property images
    SUV = True # convert PET images to SUV

    @property
    def headers(self):
        """ Get pydicom headers from values in database. Pydicom headers 
        are generated from database content. """
        if len(self.files) > self.MAX_FILES:
            print('Number of files exceeds MAX_FILES property')
            raise IOError
        
        if self._headers is not None:
            return self._headers
        
        if self.instance_count < 1:
            self._headers = []
            return self.headers
        
        headers = []
        uids = self.SOPInstanceUID
        if not isinstance(uids, list):
            uids = [uids]
       
        headers = [self.header_for_uid(uid) for uid in uids]
        
        if len(headers) == 1:
            headers = headers[0]
            
        self._headers = headers
                
        return self._headers
    
    def header_for_uid(self, sopinstanceuid):
        db = self.query(SOPInstanceUID = sopinstanceuid)
        header_dict = {}
        #return db.dicom_tag_names
        for tag_name in db.dicom_tag_names:
            value = db.get_column(tag_name, unique=True, sort=False, parse=False)[0]
            #print(value)
            header_dict[tag_name] = value
        header = Parser.dataset_from_dict(header_dict)
        return header
            
    @property
    def files(self):
        """ List of dicom files that will be read to an image or images. """
        # must be implemented by subclass
        raise NotImplementedError
    
    @property
    def image(self):
        """ Returns an sitk image for the files in the files property.
            All files must belong to the same dicom series
            (same SeriesInstanceUID). """
        
        if self._image is not None:
            return self._image
        
        assert self.series_count == 1
        
        series_uid = self.SeriesInstanceUID
        
        if hasattr(self, 'SliceLocation'):
            sort_by = 'SliceLocation'
        elif hasattr(self, 'InstanceNumber'):
            sort_by = 'InstanceNumber'
        else:
            self.logger.error('Slice Sorting Failed Before Reading!')
            sort_by = None
            
        to_read = self.query(SeriesInstanceUID=series_uid, sort_by=sort_by)
        
        image = read_serie(to_read.files, SUV=False, 
                           issorted=True, folder=to_read.folder)
 
        # get first uid from file
        uid = self.SOPInstanceUID
        if isinstance(uid, list):
            uid = uid[0]
        # generate header with SUV metadata
        header = self.header_for_uid(uid)
        
        # calculate suv scale factor
        try:
            bqml_to_suv = suv_scale_factor(header)
        except:
            if self.SUV:
                raise
            
        if self.SUV:
            image *= bqml_to_suv
        
        image.bqml_to_suv = bqml_to_suv
        return image

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

        if self._images is not None:
            return self._images
        
        assert hasattr(self, SimpleDicomToolkit.SERIESINSTANCEUID)
        
        images = {}
        
        for uid in self.SeriesInstanceUID:
            images[uid] = self.query(SeriesInstanceUID=uid).image
        
        self._images = images
        return self._images

    


def read_files(file_list):
    """ Read a file or list of files using SimpleTIK. A file list will be
         read as an image series in SimpleITK. """
    if len(file_list) == 1:
        file_list = file_list[0]
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


def read_serie(files, rescale=True, SUV=False, issorted = False, folder=None):
    """ Read a single image serie from a dicom database to SimpleITK images.

        series_uid: Define the SeriesInstanceUID to be read from the database.
                    When None (default) it is assumed that the database
                    contains a single image series (otherwise an error
                    is raised).

        split_acquisitions: Returns seperate images for each acquisition number.
        """
    if not(issorted) and len(files) > 1:
        raise ImportError
    
    if folder is not None:
        files = [os.path.join(folder, file) for file in files]

    image = read_files(files)

#    if rescale:
#        print('Rescaling image')
#        slope, intercept = rescale_values(dicom_files)
#        image *= slope
#        image += intercept


    # calculate and add a SUV scaling factor for PET.
    if SUV:
        factor = suv_scale_factor(pydicom.read_file(files[0], 
                                                    stop_before_pixels=True))
        image *= factor
        image.BQML_TO_SUV = factor
        image.SUB_TO_BQML = 1/factor
    return image

def suv_scale_factor(header):
    """ Calculate the SUV scaling factor (Bq/cc --> SUV) based on information
    in the header. Works on Siemens PET Dicom Headers. """

    # header = image.header
    # calc suv scaling
    nuclide_info   = header.RadiopharmaceuticalInformationSequence[0]
    
    parse = lambda x: dateutil.parser.parse(x)
    series_date = parse(header.SeriesDate).date()
    series_time = parse(header.SeriesTime).time()
    injection_time = parse(nuclide_info.RadiopharmaceuticalStartTime).time()
    
    nuclide_dose   = float(nuclide_info.RadionuclideTotalDose)
    
    series_dt      = datetime.datetime.combine(series_date, series_time)
    injection_dt   = datetime.datetime.combine(series_date, injection_time)


    half_life      = float(nuclide_info.RadionuclideHalfLife)

    patient_weight = float(header.PatientWeight)

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

    return slope, intercept

