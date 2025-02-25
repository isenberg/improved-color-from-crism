# Forked https://github.com/AsterAphelion/color-from-crism limited to VIS processing
# with improved instrument calibration for CRISM VNIR 362nm - 1053nm.
# The spectrum of map-projected targeted reduced data records (*if*mtr3.lbl/img pairs)
# in the VNIR range shows an unexplainable linear gradient reducing the reflectance (I/F)
# of plain white surface by a factor of 2 to 3 at the short wavelength VNIR spectrum end at 362nm
# compared to the long wavelength VNIR spectrum end at 1053nm.
# White surfaces like northern polar cap snow is expected to show a flat I/F spectrum,
# as can be verified by telescope observations form Earth or from other cameras in Mars orbit.
#
# For the improved calibration, the spectrum of white snow surfaces extracted from
# existing CRISM VNIR if*mtr3 images is extraced with http://crism.jhuapl.edu/JCAT as 
# mtrdr_whiteflat.csv and loaded by crism.py.
#
# The image-viewer's illuminant is changed from D65 to the more common D55 of current screens.
#
# Example images shows white surface:
# frt000128f3_07_if165j_mtr3
#
# Example usage to create calibrated output file hrl000095c7_07_if182j_mtr3_VIS.png:
# python3 crism.py mtrdr_to_color --file=hrl000095c7_07_if182j_mtr3.lbl --name=hrl000095c7_07_if182j_mtr3
#
# Required input files available on https://ode.rsl.wustl.edu/mars/mapsearch
# as layers -> Derived Map-projected MTRDR: *if*_mtr3.lbl, *if*_mtr3.img
#
# This calibration is not yet complete, but already shows an improvement in the expected direction.

import rasterio
import numpy as np
import spectres as spec
import fire

#Initialize color_system.py (this segment of code by 'christian' on the SciPython blog)
#See: https://scipython.com/blog/converting-a-spectrum-to-a-colour/

#This is the core of the code, tinker at your own risk.
def xyz_from_xy(x, y):
        """Return the vector (x, y, 1-x-y)."""
        return np.array((x, y, 1-x-y))

class ColourSystem:
    """A class representing a colour system.

    A colour system defined by the CIE x, y and z=1-x-y coordinates of
    its three primary illuminants and its "white point"."""

    # The CIE colour matching function for 380 - 780 nm in 5 nm intervals
    cmf = np.loadtxt('matching_functions/cie-cmf.txt', usecols=(1,2,3))

    def __init__(self, red, green, blue, white):
        """Initialise the ColourSystem object.

        Pass vectors (ie NumPy arrays of shape (3,)) for each of the
        red, green, blue  chromaticities and the white illuminant
        defining the colour system."""

        # Chromaticities
        self.red, self.green, self.blue = red, green, blue
        self.white = white
        # The chromaticity matrix (rgb -> xyz) and its inverse
        self.M = np.vstack((self.red, self.green, self.blue)).T 
        self.MI = np.linalg.inv(self.M)
        # White scaling array
        self.wscale = self.MI.dot(self.white)
        # xyz -> rgb transformation matrix
        self.T = self.MI / self.wscale[:, np.newaxis]

    def xyz_to_rgb(self, xyz, out_fmt=None):
        """Transform from xyz to rgb representation of colour.

        The output rgb components are normalized on their maximum
        value. If xyz is out the rgb gamut, it is desaturated until it
        comes into gamut."""

        rgb = self.T.dot(xyz)
        if np.any(rgb < 0):
            # We're not in the RGB gamut: approximate by desaturating
            w = - np.min(rgb)
            rgb += w

        return rgb

    def spec_to_xyz(self, spec):
        """Convert a spectrum to an xyz point.

        The spectrum must be on the same grid of points as the colour-matching
        function, self.cmf: 380-780 nm in 5 nm steps."""

        XYZ = np.sum(spec[:, np.newaxis] * self.cmf, axis=0)
        den = np.sum(XYZ)
        if den == 0.:
            return XYZ
        return XYZ / den

    def spec_to_rgb(self, spec, out_fmt=None):
        """Convert a spectrum to an rgb value."""

        xyz = self.spec_to_xyz(spec)
        return self.xyz_to_rgb(xyz, out_fmt)

illuminant_D50 = xyz_from_xy(0.3457, 0.3585)
illuminant_D55 = xyz_from_xy(0.3324, 0.3474)
illuminant_D65 = xyz_from_xy(0.3127, 0.3291)
illuminant_D75 = xyz_from_xy(0.2990, 0.3149)
cs_hdtv = ColourSystem(red=xyz_from_xy(0.67, 0.33),
                       green=xyz_from_xy(0.21, 0.71),
                       blue=xyz_from_xy(0.15, 0.06),
                       white=illuminant_D55)

cs_smpte = ColourSystem(red=xyz_from_xy(0.63, 0.34),
                        green=xyz_from_xy(0.31, 0.595),
                        blue=xyz_from_xy(0.155, 0.070),
                        white=illuminant_D55)

cs_srgb = ColourSystem(red=xyz_from_xy(0.64, 0.33),
                       green=xyz_from_xy(0.30, 0.60),
                       blue=xyz_from_xy(0.15, 0.06),
                       white=illuminant_D55)


##Defining a few internal functions to help us on our journey.

#Some frequently-used few-liner functions
def find_band(array, value):
    """One-liner to find the index value of the nearest band to a given 
    wavelength value."""
    idx = (np.abs(array - value)).argmin()
    return idx

def quicknorm(data):
    data = (data-np.amin(data))/np.amax(data)
    return data

def calculate_luminance(weights, cube):
    """Function to calculate an image through a filter given the filter transmission properties
    (weights) from a cube."""
    ##Design philosophy: I am integrating the filter bandpass by first multiplying each cube channel
    #by the filter transmission at that channel, then summing the result. To maintain the relative 
    #brighnesses of each filter, I then find the average I/F value for the wavelength range spanned by
    #the cube, and then add an offset value to the calculated filter.
    
    #This is mostly to make sure that the weights work for low transmission filters. Setup for later
    #before we modify the weights variable for filter integration.
    if np.amax(weights) < 0.05:
        weights = weights * 100
        short = np.where(weights >= 0.05)[0][0]
        long = np.where(weights >= 0.05)[0][-1]
        weights = weights / 100
    
    else:
        short = np.where(weights >= 0.05)[0][0]
        long = np.where(weights >= 0.05)[0][-1]
    
    if short == long:
        long += 1      
    
    #Now integrate the filter
    weights = weights/np.sum(weights)
    lumin = np.average(cube, axis=2, weights=weights)
    
    #Apply offset to "true" I/F
    lumin += (np.mean(cube[:,:,short:long]) - np.mean(lumin))

    return(lumin)

def convert_uint16(cube):
    """Converts cube data (float format) to 16-bit unsigned integer."""
    cube = cube * 65535
    cube = cube.astype(np.uint16)
    return(cube)

#MTRDR pre-processing functions
def modify_mtrdr_axis():
    """Crops the image cube to the given wavelength range."""
    mtrdr_axis = np.genfromtxt("matching_functions/mtrdr_axis.tab", delimiter=",")
    mtrdr_axis = mtrdr_axis[:,2]
    
    #Fill in the gaps where bad bands are present
    #Blue gap - 380-436 nm
    add_waves = np.linspace(377.58, 429.62, num=9)
    add_waves = np.around(add_waves, decimals=2)
    mtrdr_axis = np.concatenate((add_waves, mtrdr_axis))
    
    #NIR bad bands 637-710 nm
    bad_band_fill = np.linspace(637.96, 703.1, num=10)
    bad_band_fill = np.around(bad_band_fill, decimals=2)
    mtrdr_axis = np.insert(mtrdr_axis, 40, bad_band_fill, axis=0)
    
    return(mtrdr_axis)

def mtrdr_crop_bands(image_cube, wave_list):
    """Crops the image cube to the given wavelength range."""
    mtrdr_axis = modify_mtrdr_axis()
    
    short = find_band(mtrdr_axis, wave_list[0])
    long = find_band(mtrdr_axis, wave_list[1])
    crop_cube = image_cube[short:long, :, :]
    
    return(crop_cube)
    
def mtrdr_color_matching(wave_list):
    """Adjusts the CIE color matching function to span the given wavelength range."""
    #Import CIE color matching function
    #Index 0 - wavelengths, Index 1 - red matching function
    #Index 2 - green matching function, Index 3 - blue matching function
    cie_matrix = np.genfromtxt("matching_functions/cie-cmf.txt")

    #Import tab-delimited file of wavelength axis
    mtrdr_axis = modify_mtrdr_axis()
    
    #Find mtrdr axis indices with closest values to user-specified values.
    short = find_band(mtrdr_axis, wave_list[0])
    long = find_band(mtrdr_axis, wave_list[1])
    
    ##Now use normalization to rescale wavelength axis of CIE color matching functions
    #to user-specified wavelength range...
    cie_matrix[:,0] = (mtrdr_axis[long] - mtrdr_axis[short]) / (cie_matrix[-1,0] - cie_matrix[0,0]) * (cie_matrix[:,0]-cie_matrix[-1,0]) + mtrdr_axis[long]
    
    #..then resample CIE function values using MTRDR axis values
    red = spec.spectres(mtrdr_axis[short:long], cie_matrix[:,0], cie_matrix[:,1], fill=0, verbose=False)
    green = spec.spectres(mtrdr_axis[short:long], cie_matrix[:,0], cie_matrix[:,2], fill=0, verbose=False)
    blue = spec.spectres(mtrdr_axis[short:long], cie_matrix[:,0], cie_matrix[:,3], fill=0, verbose=False)
    
    #Concatenate the results
    new_mat = np.stack([red, green, blue], axis=-1)
    return(new_mat)


def format_mtrdr(cube):
    """Prepare MTRDR data cube for color production by filling in missing bands."""
    
    ##Grab the modified MTRDR axis. To document some index values I'm using in this function:
    #Indices 0-9 in this axis represent the 377-436 nm channels, which need to be calculated 
    #through extrapolation and are needed to produce the blue channel in the color output. 
    #Indices 40-50 represent the missing 631-709 nm channels, needed to produce the red channel 
    #in the color output. 
    mtrdr_axis = modify_mtrdr_axis()
    
    ##Extrapolate the missing bands (377-436 nm) necessary for blue. To do this, I am 
    #creating a dummy channel by averaging the values from the first six bands. This creates
    #an array of 9 copies of the average of the first 6 valid bands. Later I will subtract
    #a slope constant subtracted from each band to extrapolate the radiance of each band in
    #this wavelength range.
    interp_channel = np.average(cube[0:6], axis=0)
    interp_channel = np.tile(interp_channel, (9,1,1))
    
    #Band-to-band noise is reduced by calculating the slope from three channel pairs and 
    #averaging the result. This step produces a blue slope for each pixel in the image.
    slope = (cube[2] - cube[6]) / (mtrdr_axis[6] - mtrdr_axis[2])
    slope2 = (cube[1] - cube[5]) / (mtrdr_axis[5] - mtrdr_axis[1])
    slope3 = (cube[0] - cube[4]) / (mtrdr_axis[4] - mtrdr_axis[0])
    slope = (slope + slope2 + slope3) / 3
    
    #Next, we tile the slope so that the array shape matches the number of bands we need to
    #fill in, then multiply the slope by the distance from the first good band. The resulting
    #array is then added to the dummy bands to produce the extrapolated data array.
    slope = np.tile(slope, (9,1,1))
    multiplier = mtrdr_axis[9] - mtrdr_axis[0:9]
    multiplier = multiplier[:, np.newaxis, np.newaxis]
    slope = slope * multiplier
    interp_channel += slope
    
    cube = np.concatenate((interp_channel, cube), axis=0)
    
    #Now repeat the process to fill in the VIS-NIR bad bands.
    interp_channel = np.tile(cube[39], (10,1,1))

    slope = (cube[37] - cube[40])/(mtrdr_axis[50] - mtrdr_axis[39])
    slope2 = (cube[38] - cube[41])/(mtrdr_axis[51]- mtrdr_axis[38])
    slope3 = (cube[39] - cube[42])/(mtrdr_axis[52]- mtrdr_axis[37])
    slope = (slope + slope2 + slope3) / 3

    slope = np.tile(slope, (10, 1, 1))
    multiplier = mtrdr_axis[40:50] - mtrdr_axis[39]
    multiplier = multiplier[:, np.newaxis, np.newaxis]
    slope = slope * multiplier

    interp_channel += slope
    
    #Now to insert the VIS-NIR bad bands into the array. This might be faster and more 
    #memory efficient using np.insert, but my brain hurts trying to figure out that function. 
    #So for now, using the inefficient way.
    
    #Blue side of the bad bands
    short = cube[0:40]
    #Red side of the bad bands
    long = cube[40::]

    intermed = np.concatenate((short, interp_channel), axis=0)
    cube = np.concatenate((intermed, long), axis=0)
    
    return(cube)

def color_from_cube(cube, cs, mode="raw"):
    """Core functionality for calculating human perceptual color from CRISM MTRDR."""
    #Transpose array to put the wavelength axis last - personal preference
    cube = cube.transpose(1,2,0)
    
    #We will lose luminance data once we calculate chromaticity, so before transforming the shape
    #of the data cube, I'm going to calculate luminance images by scaling the brightness of each band
    #by the CIE scaling factor at that band, then integrating across the entire wavelength range.
    
    #I'm doing this step here because when calculating color from spacecraft filters in other functions
    #the data cubes remain three-dimensional. It's easier to run this step here while the cube is still
    #three-dimensional than it is to add a dimensionality argument to calculate_luminance() and specify
    #the dimensionality of the data every time.
    
    # as humans are viewing the image,
    # no artifical simulation of the human vision system via CIE cmf is needed.
    # Evalulating results with flat cmf replacement.
    #weights = cs.cmf.copy()
    weights = np.ones([61,3])

    # CRISM VNIR 362nm - 1053nm calibration correction,
    # quantized into crism.py internal convention of starting at 380nm in 5 nm intervals.
    # Based on white surface spectrum saved saved with http://crism.jhuapl.edu/JCAT
    # for example from north polar snow surfaces in frt000128f3_07_if165j_mtr3.img.
    w = 380
    dw = 5
    whiteflatraw = np.genfromtxt("mtrdr_whiteflat.csv", delimiter=",")
    whiteflatraw = whiteflatraw[:, [1,2]]
    whiteflatraw_bands = whiteflatraw[:, 0]
    cube_bands = cube.shape[2]
    whiteflat = np.zeros(cube_bands, dtype=float)
    whiteflatraw_max = 0
    for i in range(0, cube_bands):
        whiteflat[i] = whiteflatraw[find_band(whiteflatraw_bands, w)][1]
        whiteflatraw_max = max(whiteflat[i], whiteflatraw_max)
        w = w + dw
    whiteflat = whiteflatraw_max / whiteflat
    for i in range(0, cube_bands):
        cube[:,:,i] = whiteflat[i] * cube[:,:,i]

    blu_lumin = calculate_luminance(weights[:,0], cube)
    grn_lumin = calculate_luminance(weights[:,1], cube)
    red_lumin = calculate_luminance(weights[:,2], cube)
    
    #Merge luminance cubes together, then perform a contrast stretch. Adding 2% buffers to the minimum
    #and maximum values to avoid histogram clipping.
    lumin = np.stack((blu_lumin, grn_lumin, red_lumin), axis=0)
    lumin = (lumin - (np.amin(lumin) - (0.02*np.amin(lumin)))) / ((np.amax(lumin) + (0.02*np.amax(lumin))))

    #Now reshape the data array so that it's one dimensional and runs more quickly in the loop that
    #calculates chromaticity values (I'm not sure if the chromaticity calculation can be set up to take
    #advantge of broadcasting ufuncs. 
    rows = cube.shape[0]
    cols = cube.shape[1]
    pixels = rows*cols
    cube = cube.reshape(pixels, cube.shape[2])

    #Create a new cube to handle the interpolated color data
    clone_cube = np.empty((cube.shape[0], 3))

    #Convert the wavelength range to RGB values. If this can be broadcast this would
    #run much more quickly.
    # todo: this operation can be done must faster with numpy and broadcasting ufuncs
    for pixel in range(0, pixels):
        clone_cube[pixel] = cs.spec_to_rgb(cube[pixel])
        
    #When chromaticity values integrate outside of the [0-1] range, they need to be scaled back to 
    #that range to be displayed within the chosen colorspace. The ColourSystem class as written by
    #"Christian" normalized on a per-pixel basis, which destroys relative color information. This was
    #dealt with by removing a normalization statement from the xyz_to_rgb function within the class
    #definition.
    
    #We still need to normalize back to the [0-1 range], which we're doing here with the quicknorm()
    #function. "Raw" normalization preserves the relative color channel brightnesses by simply stretching
    #between the highest chromaticity(typically red) and lowest chromaticity (typically blue) values.
    #"WB" independently normalizes each color channel, similar to the output provided in the official
    #CRISM parameter products. 

    if mode=="raw":
        clone_cube = quicknorm(clone_cube)

    if mode=="wb":
        for channel in range(0, clone_cube.shape[1]):
            clone_cube[:,channel] = quicknorm(clone_cube[:,channel])
        
    #Reshape pixels back to original x,y orientation
    cube = clone_cube.reshape(rows, cols, 3).transpose(2, 0, 1)
    
    #Add luminance data to cube
    cube[0,:,:] = cube[0,:,:] * lumin[0]
    cube[1,:,:] = cube[1,:,:] * lumin[1]
    cube[2,:,:] = cube[2,:,:] * lumin[2]
    
    #Convert to unsigned 16-bit
    cube = convert_uint16(cube)
    
    return(cube)

def mtrdr_to_color(file, name, standard_params=True, new_params=None):
    """Function to produce perceptually-accurate color from CRISM MTRDR data."""

    with rasterio.open(file) as src:
        profile = src.profile
        img = src.read()
    cs = cs_srgb

    #Make null values = 0 so that it doesn't break when doing rgb conversion
    #Also need to convert the null pixels outside of image to 0.
    img[img < 0] = 0
    img[img >= 1] = 0

    img = format_mtrdr(img)

    profile.update(
        dtype = rasterio.uint16,
        count = 3,
        driver = 'PNG'
    )
    
    if standard_params == True:
        process_list = ["VIS"]
        mode_list = ["raw"]
        
        for param, mode in zip(process_list, mode_list):

            if param == "VIS":
                #Imitate VIS browse product summarizing wavelength range from 380 to 780 nm
                wave_range = [380, 780]

            if param == "FAL":
                #Imitate FAL browse product summarizing wavelength range from 1.01 to 2.60 microns
                wave_range = [1010, 2600]

            if param == "FEM":
                #Integrate over 750 nm to 1200nm to capture variability in Fe oxidation state/mineralogy
                wave_range = [750, 1200]

            if param == "MAF":
                #Integrate over 800 nm to 2 micron wavelength range capturing variability in
                #primary basaltic minerals.
                wave_range = [800, 2000]

            if param == "PHY":
                #Integrate over 1.8 to 2.3 micron wavelength range capturing variability in 
                #clay mineralogy.
                wave_range = [1800, 2300]

            if param == "FAR":
                #Integrate over the longwave detector (2.8 microns to 3.6 microns)
                wave_range = [2800, 3900]

            if param == "CAR":
                #Integrate from 2.8 microns to 3.4 microns capturing region of water and carbonate
                wave_range = [2900, 3400]

            
            cube = mtrdr_crop_bands(img, wave_range)
            ColourSystem.cmf = mtrdr_color_matching(wave_range)
            cube = color_from_cube(cube, cs, mode=mode)
            #Export PNG file
            with rasterio.open(name+"_"+param+".png", 'w', **profile) as out:
                out.write(cube)
            
    if new_params != None:
        
        for item in new_params:
            
            if len(item) != 2:
                print("Error: Wavelength list appears to be incorrectly formatted.")
                print("New parameters should be in form [[wave1, wave2], [wave1, wave2], ...]")
                
            else:
                cube = mtrdr_crop_bands(img, item)
                ColourSystem.cmf = mtrdr_color_matching(item)
                cube = color_from_cube(cube, cs, mode=mode)
                with rasterio.open(name+"_"+str(item[0])+"_"+str(item[1])+".png", 'w', **profile) as out:
                    out.write(cube)
    
    pass



def mtrdr_to_cassis(file, fname, color="IPB"):
    
    ##Data I/O and formatting
    with rasterio.open(file) as src:
        profile = src.profile
        cube = src.read()
    
    cube = format_mtrdr(cube)
    cube = mtrdr_crop_bands(cube, [380, 1100])
    cube = cube.transpose(1,2,0)
    cube = np.ma.masked_values(cube, 65535)
    
    #Developer note: CaSSIS filter responses are stored in the following order:
    #[0] - MTRDR wavelength; [1] - Blue; [2] - PAN; [3] - Red; [4] - NIR
    
    #Filter information retrieved from the Spanish Virtual Observatory Filter Profile Repository
    filter_response = np.genfromtxt("matching_functions/cassis-response-mtrdr.txt", delimiter="\t")
    
    ##Calculate filter images filters via integration
    
    blu = calculate_luminance((filter_response[:, 1]), cube)
    pan = calculate_luminance((filter_response[:, 2]), cube)
    red = calculate_luminance((filter_response[:, 3]), cube)
    nir = calculate_luminance((filter_response[:, 4]), cube)
    

    if color == "IPB":
        export = np.stack((nir, pan, blu))
        
    elif color == "IRB":
        export = np.stack((red, pan, blu))
        
    elif color == "ENH":
        enh_red = red/pan
        enh_grn = pan/blu
        enh_blu = pan/nir
        
        enh_red += np.average(enh_grn) - np.average(enh_red)
        enh_blu += np.average(enh_grn) - np.average(enh_blu)
        export = np.stack((enh_red, enh_grn, enh_blu))
        
    else:
        print("Invalid color keyword, use 'IPB', 'IRB', or 'ENH'.")
    
    export = (export - (np.amin(export) - (0.02*np.amin(export)))) / ((np.amax(export) + (0.02*np.amax(export))))    
    export = convert_uint16(export)
    
    #Update profile for color export
    profile.update(
        dtype = rasterio.uint16,
        count = 3,
        driver = 'PNG'
    )
    
    with rasterio.open(fname+"_"+color+".png", 'w', **profile) as out:
                out.write(export)
                
    return


def mtrdr_to_hirise(file, fname, color="IRB"):
    
    ##Data I/O and formatting
    with rasterio.open(file) as src:
        profile = src.profile
        cube = src.read()
    
    cube = format_mtrdr(cube)
    cube = mtrdr_crop_bands(cube, [380, 1100])
    cube = cube.transpose(1,2,0)
    cube = np.ma.masked_values(cube, 65535)
    
    #Developer note: HiRISE filter responses are stored in the following order:
    #[0] - MTRDR wavelength; [1] - NIR; [2] - Red; [3] - Blue-Green
    
    #Filter information retrieved from the Spanish Virtual Observatory Filter Profile Repository
    filter_response = np.genfromtxt("matching_functions/hirise-response-mtrdr.txt", delimiter="\t")
    
    ##Calculate filter images filters via integration
    
    nir = calculate_luminance((filter_response[:, 1]), cube)
    red = calculate_luminance((filter_response[:, 2]), cube)
    bgr = calculate_luminance((filter_response[:, 3]), cube)

    if color == "IRB":
        export = np.stack((nir, red, bgr))
        
    elif color == "RGB":
        #If RGB is requested, calculate synthetic blue filter according to HiRISE team formula
        blu = (bgr * 2) - (red * 0.3)
        #The blue channel tends to be bright, so applying an offset to simulate the I/F of blue
        #light in CRISM.
        blu += np.average(cube[:,:,0:10]) - np.average(blu)
        export = np.stack((red, bgr, blu))
        
    elif color == "ENH":
        enh_red = nir/red
        enh_grn = nir/bgr
        enh_blu = red/bgr
        
        enh_red += np.average(enh_grn) - np.average(enh_red)
        enh_blu += np.average(enh_grn) - np.average(enh_blu)
        export = np.stack((enh_red, enh_grn, enh_blu))
        
    else:
        print("Invalid color keyword, use 'IRB' or 'RGB'.")
    
    export = (export - (np.amin(export) - (0.02*np.amin(export)))) / ((np.amax(export) + (0.02*np.amax(export))))    
    export = convert_uint16(export)
    
    #Update profile for color export
    profile.update(
        dtype = rasterio.uint16,
        count = 3,
        driver = 'PNG'
    )
    
    with rasterio.open(fname+"_"+color+".png", 'w', **profile) as out:
                out.write(export)
                
    return


def mtrdr_to_hrsc(file, fname, color="IGB", lumin=False):
    
    ##Data I/O and formatting
    with rasterio.open(file) as src:
        profile = src.profile
        cube = src.read()
    
    cube = format_mtrdr(cube)
    cube = mtrdr_crop_bands(cube, [380, 1100])
    cube = cube.transpose(1,2,0)
    cube = np.ma.masked_values(cube, 65535)
    
    #Developer note: HRSC filter responses are stored in the following order:
    #[0] - MTRDR wavelength; [1] - Nadir; [2] - NIR; [3] - Red; [4] - Green; [5] - Blue;
    #[6] - Photometry; [7] - Stereo
    
    #Approximately 15% of the light entering the HRSC blue filter in the N-UV is not visible
    #to CRISM, so the filter response is a little different from reality.
    
    #Filter information retrieved from the Spanish Virtual Observatory Filter Profile Repository
    filter_response = np.genfromtxt("matching_functions/hrsc-response-mtrdr.txt", delimiter="\t")
    
    ##Calculate filter images filters via integration
    
    nad = calculate_luminance((filter_response[:, 1]), cube)
    nir = calculate_luminance((filter_response[:, 2]), cube)
    red = calculate_luminance((filter_response[:, 3]), cube)
    grn = calculate_luminance((filter_response[:, 4]), cube)
    blu = calculate_luminance((filter_response[:, 5]), cube)
    pho = calculate_luminance((filter_response[:, 6]), cube)
    ste = calculate_luminance((filter_response[:, 7]), cube)
    
    if color == "IGB":
        export = np.stack((nir, grn, blu))
        
    elif color == "IRB":
        export = np.stack((nir, red, blu))
        
    elif color == "RGB":
        export = np.stack((red, grn, blu))
        
    else:
        print("Invalid color keyword, use 'IGB', 'IRB', or 'RGB'.")
    
    export = (export - (np.amin(export) - (0.02*np.amin(export)))) / ((np.amax(export) + (0.02*np.amax(export))))    
    export = convert_uint16(export)
    
    #Update profile for color export
    profile.update(
        dtype = rasterio.uint16,
        count = 3,
        driver = 'PNG'
    )
    
    with rasterio.open(fname+"_"+color+".png", 'w', **profile) as out:
                out.write(export)
    
    if lumin == False:
        return
    
    filter_list = [nad, nir, red, grn, blu, pho, ste]
    filter_names = ["ND", "IR", "RED", "GRN", "BLU", "P1", "S1"]
    
    profile.update(
        dtype = rasterio.uint16,
        count = 1,
        driver = 'PNG'
    )
    
    for item, name in zip(filter_list, filter_names):
        item = np.expand_dims(item, 0)
        item = convert_uint16(item)
        with rasterio.open(fname+"_"+name+".png", 'w', **profile) as out:
                out.write(item)
                
    return


def mtrdr_to_mastcam(file, fname, narrowband=True):
    
    ##Data I/O and formatting
    with rasterio.open(file) as src:
        profile = src.profile
        cube = src.read()
    
    cube = format_mtrdr(cube)
    cube = mtrdr_crop_bands(cube, [380, 1200])
    cube = cube.transpose(1,2,0)
    cube = np.ma.masked_values(cube, 65535)
    
    #Developer note: Mastcam filter responses are stored in the following order:
    #[0] - wavelength
    #[1-4] - bayer filters (blue, green, red)
    #[4] - Left IR-bandcut
    #[5-12] - Left narrowband filters (L1-L7)
    #[12] - Right IR-bandcut
    #[13:] - Right narrowband filters (R1-R7)
    
    filter_response = np.genfromtxt("matching_functions/mastcam-response-mtrdr.txt", delimiter="\t")
    
    ##Calculate filter images filters via integration
    
    blue = calculate_luminance((filter_response[:, 1] * filter_response[:, 4]), cube)
    green = calculate_luminance((filter_response[:, 2] * filter_response[:,4]), cube)
    red = calculate_luminance((filter_response[:, 3] * filter_response[:,4]), cube)
    
    export = np.stack((red, green, blue))
    export = (export - (np.amin(export) - (0.02*np.amin(export)))) / ((np.amax(export) + (0.02*np.amax(export))))
    filter_name = "RGB"
    
    export = convert_uint16(export)
    
    #Update profile for color export
    profile.update(
        dtype = rasterio.uint16,
        count = 3,
        driver = 'PNG'
    )
    
    with rasterio.open(fname+"_"+filter_name+".png", 'w', **profile) as out:
                out.write(export)
    
    if narrowband == False:
        return
    
    #This section probably does not have the cleanest setup. Would prefer to execute this by iterating through 
    #filters, but MastCam narrowband filters are obtained by discarding two of the Bayer filters (see Bell 
    #et al. 2016 for documentation). The Bayer filters which get dropped change filter to filter, so I'm not 
    #sure I can cleanly iterate through this in a loop.
    
    #The Bayer filters are effectively transparent in the NIR and are treated as identically transparent.
    #Here I will emulate the interpolation by averaging the three Bayer filter bandpasses before applying 
    #it to the narrowband filter.
    bayer_response = np.average(filter_response[:, 1:4], axis=1)
    
    l1 = calculate_luminance((filter_response[:, 5] * filter_response[:,2]), cube)
    l2 = calculate_luminance((filter_response[:, 6] * filter_response[:,1]), cube)
    l3 = calculate_luminance((filter_response[:, 7] * filter_response[:,3]), cube)
    l4 = calculate_luminance((filter_response[:, 8] * filter_response[:,3]), cube)
    l5 = calculate_luminance((filter_response[:, 9] * bayer_response), cube)
    l6 = calculate_luminance((filter_response[:, 10]* bayer_response), cube)
    
    r1 = calculate_luminance((filter_response[:,13] * filter_response[:,2]), cube)
    r2 = calculate_luminance((filter_response[:,14] * filter_response[:,1]), cube)
    r3 = calculate_luminance((filter_response[:,15] * filter_response[:,3]), cube)
    r4 = calculate_luminance((filter_response[:, 16]* bayer_response), cube)
    r5 = calculate_luminance((filter_response[:, 17]* bayer_response), cube)
    r6 = calculate_luminance((filter_response[:, 18]* bayer_response), cube)
    
    
    filter_list = [l1, l2, l3, l4, l5, l6, r1, r2, r3, r4, r5, r6]
    filter_names = ["L1_527nm", "L2_445nm", "L3_751nm", "L4_676nm", "L5_867nm",
                   "L6_1012nm", "R1_527nm", "R2_447nm", "R3_805nm", "R4_908nm",
                   "R5_937nm", "R6_1013nm"]
    
    profile.update(
        dtype = rasterio.uint16,
        count = 1,
        driver = 'PNG'
    )
    
    for item, name in zip(filter_list, filter_names):
        item = np.expand_dims(item, 0)
        item = convert_uint16(item)
        with rasterio.open(fname+"_"+name+".png", 'w', **profile) as out:
                out.write(item)
                
    return


def mtrdr_to_mastcamz(file, fname, narrowband=True):
    
    ##Data I/O and formatting
    with rasterio.open(file) as src:
        profile = src.profile
        cube = src.read()
    
    cube = format_mtrdr(cube)
    cube = mtrdr_crop_bands(cube, [380, 1100])
    cube = cube.transpose(1,2,0)
    cube = np.ma.masked_values(cube, 65535)
    
    #Developer note: Mastcam filter responses are stored in the following order:
    #[0] - wavelength
    #[1-4] - bayer filters (blue, green, red)
    #[4-10] - Left narrowband filters (L1-L6)
    #[10:] - Right narrowband filters (R2-R7) (R1 is duplicate of L1 and not included)
    
    #Filter responses are adapted from Hayes et al. 2021 (Pre-Flight Calibration of the Mars
    #2020 Rover Mastcam Zoom (Mastcam-Z) Multispectral Stereoscopic Imager). In-band responses
    #were primarily used, with out-of-band responses added when these responses were within an 
    #order of magnitude of peak response.
    
    filter_response = np.genfromtxt("matching_functions/mastcamz-response-mtrdr.txt", delimiter="\t")
    
    ##Calculate filter images filters via integration
    
    blue = calculate_luminance(filter_response[:, 1], cube)
    green = calculate_luminance(filter_response[:, 2], cube)
    red = calculate_luminance(filter_response[:, 3], cube)
    
    export = np.stack((red, green, blue))
    print(export)
    export = (export - (np.amin(export) - (0.02*np.amin(export)))) / ((np.amax(export) + (0.02*np.amax(export))))
    filter_name = "RGB"
    
    export = convert_uint16(export)
    
    #Update profile for color export
    profile.update(
        dtype = rasterio.uint16,
        count = 3,
        driver = 'PNG'
    )
    
    with rasterio.open(fname+"_"+filter_name+".png", 'w', **profile) as out:
                out.write(export)
    
    if narrowband == False:
        return
    
    #Unlike the Mastcam setup, where filter calibrations did not account for the Bayer filter,
    #the Mastcam-Z files provided the filter response through each of the red, green, and blue Bayer
    #filters. L6 uses only the blue Bayer response, L5 the green Bayer response, and L4 and L3 the 
    #red Bayer response. 
    
    #I am assuming that the NIR filters take the same approach used on Mastcam and simply treat the 
    #Bayer filters as more or less equally transparent for the purposes of Bayer interpolation. The 
    #filter response files averaged the filter responses of the convolved NIR and Bayer filters. 
    
    #Happy to change this if it is incorrect!
    
    l1 = calculate_luminance(filter_response[:, 4], cube)
    l2 = calculate_luminance(filter_response[:, 5], cube)
    l3 = calculate_luminance(filter_response[:, 6], cube)
    l4 = calculate_luminance(filter_response[:, 7], cube)
    l5 = calculate_luminance(filter_response[:, 8], cube)
    l6 = calculate_luminance(filter_response[:, 9], cube)

    r2 = calculate_luminance(filter_response[:,10], cube)
    r3 = calculate_luminance(filter_response[:,11], cube)
    r4 = calculate_luminance(filter_response[:, 12], cube)
    r5 = calculate_luminance(filter_response[:, 13], cube)
    r6 = calculate_luminance(filter_response[:, 14], cube)
    
    
    filter_list = [l1, l2, l3, l4, l5, l6, r2, r3, r4, r5, r6]
    filter_names = ["L1_800nm", "L2_754nm", "L3_677nm", "L4_605nm", "L5_528nm",
                   "L6_442nm", "R2_866nm", "R3_910nm", "R4_939nm",
                   "R5_978nm", "R6_1022nm"]
    
    profile.update(
        dtype = rasterio.uint16,
        count = 1,
        driver = 'PNG'
    )
    
    for item, name in zip(filter_list, filter_names):
        item = np.expand_dims(item, 0)
        item = convert_uint16(item)
        with rasterio.open(fname+"_"+name+".png", 'w', **profile) as out:
                out.write(item)
                
    return


def mtrdr_to_pancam(file, fname, color="RGB", narrowband=True):
    
    ##Data I/O and formatting
    with rasterio.open(file) as src:
        profile = src.profile
        cube = src.read()
    
    cube = format_mtrdr(cube)
    cube = mtrdr_crop_bands(cube, [380, 1150])
    cube = cube.transpose(1,2,0)
    cube = np.ma.masked_values(cube, 65535)
    
    #Developer note: PanCam filter responses are stored in the following order:
    #[0] - MTRDR wavelength; [1:8] - L1-L7; [8:] - R1-R7
    
    #Filter information retrieved from the Spanish Virtual Observatory Filter Profile Repository
    filter_response = np.genfromtxt("matching_functions/pancam-response-mtrdr.txt", delimiter="\t")
    
    ##Calculate filter images filters via integration
    
    l1 = calculate_luminance((filter_response[:, 1]), cube)
    l2 = calculate_luminance((filter_response[:, 2]), cube)
    l3 = calculate_luminance((filter_response[:, 3]), cube)
    l4 = calculate_luminance((filter_response[:, 4]), cube)
    l5 = calculate_luminance((filter_response[:, 5]), cube)
    l6 = calculate_luminance((filter_response[:, 6]), cube)
    l7 = calculate_luminance((filter_response[:, 7]), cube)
    r1 = calculate_luminance((filter_response[:, 8]), cube)
    r2 = calculate_luminance((filter_response[:, 9]), cube)
    r3 = calculate_luminance((filter_response[:, 10]), cube)
    r4 = calculate_luminance((filter_response[:, 11]), cube)
    r5 = calculate_luminance((filter_response[:, 12]), cube)
    r6 = calculate_luminance((filter_response[:, 13]), cube)
    r7 = calculate_luminance((filter_response[:, 14]), cube)
    
    if color == "RGB":
        export = np.stack((l3, l5, l7))
        
    elif color == "IRB":
        export = np.stack((l2, l5, l7))
        
    else:
        print("Invalid color keyword, use 'RGB' or 'IRB'.")
    
    export = (export - (np.amin(export) - (0.02*np.amin(export)))) / ((np.amax(export) + (0.02*np.amax(export))))    
    export = convert_uint16(export)
    
    #Update profile for color export
    profile.update(
        dtype = rasterio.uint16,
        count = 3,
        driver = 'PNG'
    )
    
    with rasterio.open(fname+"_"+color+".png", 'w', **profile) as out:
                out.write(export)
    
    if narrowband == False:
        return
    
    filter_list = [l1, l2, l3, l4, l5, l6, l7, r1, r2, r3, r4, r5, r6, r7]
    filter_names = ["L1_PAN", "L2_750nm", "L3_670nm", "L4_600nm", "L5_530nm", "L6_480nm", "L7_430nm",
                   "R1_430nm", "R2_750nm", "R3_800nm", "R4_860nm", "R5_900nm", "R6_930nm", "R7_980nm"]
    
    profile.update(
        dtype = rasterio.uint16,
        count = 1,
        driver = 'PNG'
    )
    
    for item, name in zip(filter_list, filter_names):
        item = np.expand_dims(item, 0)
        item = convert_uint16(item)
        with rasterio.open(fname+"_"+name+".png", 'w', **profile) as out:
                out.write(item)
                
    return

if __name__ == '__main__':
  fire.Fire()
