from __future__ import print_function

import numpy
import os
from datetime import datetime, timedelta

from core.loaders.GeopointsLoader import GeopointsLoader, Geopoints
from core.loaders.GribLoader import GribLoader
from .utils import (
    iter_daterange,
    adjust_leadstart,
    generate_steps,
    compute_accumulated_field,
    compute_weighted_average_field,
    compute_rms_field,
    log,
)


def run(parameters):
    BaseDateS = parameters.date_start
    BaseDateF = parameters.date_end
    Acc = parameters.accumulation
    LimSU = parameters.limit_spin_up
    Range = parameters.leadstart_range
    PathOBS = parameters.observation_path
    PathFC = parameters.forecast_path
    PathOUT = parameters.out_path

    # Set up the input/output parameters
    BaseDateS = datetime.strptime(BaseDateS, '%Y%m%d').date()
    BaseDateF = datetime.strptime(BaseDateF, '%Y%m%d').date()
    BaseDateSSTR=BaseDateS.strftime('%Y%m%d')
    BaseDateFSTR=BaseDateF.strftime('%Y%m%d')
    AccSTR = 'Acc%02dh' % Acc

    Output_file = open(PathOUT, 'w')
    Output_file.write('Ppn Forecast Verification for HRES. Base Date for FC from {0} to {1}. {2}h FC period.'.format(BaseDateSSTR, BaseDateFSTR, AccSTR))
    Output_file.write('\n\n')
    Output_file.write("'Date' and 'Time' relate to the end of the {0}h FC period.".format(AccSTR))
    Output_file.write('\n\n')
    Output_file.write('\t'.join(['DATE', 'TimeUTC', 'OBS', 'LatOBS', 'LonOBS', 'FER', 'CPR', 'TP', 'WSPD700', 'CAPE', 'SR24h', 'TimeLST']))
    Output_file.write('\n\n')


    #############################################################################################

    #PROCESSING MODEL DATA
    yield log.info("****************************************************************************************************")
    yield log.info("POST-PROCESSING SOFTWARE TO PRODUCE FORECASTS AT POINTS - ecPoint")
    yield log.info("The user is running the ecPoint-RAINFALL family, Operational Version 1")
    yield log.info("Forecast Error Ratio (FER) and Predictors for {}  hour accumulation.".format(Acc))
    yield log.info("List of predictors:")
    yield log.info("- Convective precipitation ratio, cpr = convective precipitation / total precipitation [-]")
    yield log.info("- Total precipitation, tp [mm/{}h]".format(Acc))
    yield log.info("- Wind speed of steering winds (at 700 mbar), wspd700 [m/s]")
    yield log.info("- Convective available potential energy, cape [J/kg]")
    yield log.info("- Daily accumulation of clear-sky solar radiation, sr24h [W/m2]")
    yield log.info("- Local Solar Time, lst [hours]")
    yield log.info("****************************************************************************************************")

    #Counter for the BaseDate and BaseTime to avoid repeating the same forecasts in different cases
    counterValidTimes = [0]
    obsTOT = 0
    obsUSED = 0

    for curr_date, curr_time, leadstart in iter_daterange(BaseDateS, BaseDateF):
        yield log.info('FORECAST PARAMETERS')
        yield log.info('BaseDate={} BaseTime={:02d} UTC (t+{}, t+{})'.format(
            curr_date.strftime('%Y%m%d'), curr_time, leadstart, leadstart + Acc))

        curr_date, curr_time, leadstart = adjust_leadstart(
            date=curr_date, hour=curr_time, leadstart=leadstart, limSU=LimSU,
            model_runs_per_day=2
        )
        thedateNEWSTR = curr_date.strftime('%Y%m%d')
        thetimeNEWSTR = '{:02d}'.format(curr_time)

        yield log.info(
            'BaseDate={} BaseTime={} UTC (t+{}, t+{})'.format(
                thedateNEWSTR, thetimeNEWSTR, leadstart, leadstart + Acc)
        )

        #Reading the forecasts
        if curr_date < BaseDateS or curr_date > BaseDateF:
            log.warn(
                'Requested date {} outside input date range: {} - {}'.format(
                    curr_date, BaseDateSSTR, BaseDateFSTR
                )
            )
            continue

        def get_grib_path(predictant, step):
            return os.path.join(
                PathFC, predictant, thedateNEWSTR + thetimeNEWSTR,
                '_'.join([predictant, thedateNEWSTR, thetimeNEWSTR,
                          '{:02d}'.format(step)]) + '.grib'
            )

        #Note about the computation of the sr.
        #The solar radiation is a cumulative variable and its units is J/m2 (which means, W*s/m2).
        #One wants the 24h. The 24h mean is obtained by taking the difference between the beginning and the end of the 24 hourly period
        #and dividing by the number of seconds in that period (24h = 86400 sec). Thus, the unit will be W/m2

        #6 hourly Accumulation
        if Acc == 6:
            steps = [leadstart + step for step in generate_steps(Acc)]

            # Defining the parameters for the rainfall observations
            validDateF = (
                    datetime.combine(curr_date, datetime.min.time()) +
                    timedelta(hours=curr_time) +
                    timedelta(hours=steps[-1])
            )
            DateVF = validDateF.strftime('%Y%m%d')
            HourVF = validDateF.strftime('%H')
            HourVF_num = validDateF.hour
            yield log.info('RAINFALL OBS PARAMETERS')
            yield log.info(
                'Validity date/time (end of {} hourly '
                'period) = {}'.format(Acc, validDateF)
            )

            #Looking for no repetions in the computed dates and times
            if validDateF in counterValidTimes:
                yield log.warn('Valid Date and Time already computed.')
                continue

            counterValidTimes.append(validDateF)
            dirOBS = os.path.join(PathOBS, AccSTR, DateVF)
            fileOBS = 'tp_{:02d}_{}_{}.geo'.format(Acc, DateVF, HourVF)

            obs_path = os.path.join(dirOBS, fileOBS)
            if not os.path.exists(obs_path):
                yield log.warn('File not found in DB: {}.'.format(obs_path))
                continue

            # Reading Rainfall Observations
            yield log.info('Read rainfall observation: '.format(obs_path))
            obs=GeopointsLoader(path=obs_path)
            nOBS = len(obs.values)

            if nOBS == 1:
            # which will account for the cases of zero observation in the geopoint file (because the length of the vector will be forced to 1),
            # or cases in which there is only one observation in the geopoint file
                yield log.warn('No rainfall observations: {}.'.format(fileOBS))
                continue

            obsTOT += nOBS
            if step2 <= 24:
                step1sr = 0
                step2sr = 24
            else:
                step1sr = step2 - 24
                step2sr = step2

            yield log.info('Read forecast data')

            tp1, tp2 = [GribLoader(path=get_grib_path('tp', step)) for step in steps]
            cp1, cp2 = [GribLoader(path=get_grib_path('cp', step)) for step in steps]
            u1, u2 = [GribLoader(path=get_grib_path('u700', step)) for step in steps]
            v1, v2 = [GribLoader(path=get_grib_path('v700', step)) for step in steps]
            cape1, cape2 = [GribLoader(path=get_grib_path('cape', step)) for step in steps]
            sr1, sr2 = [GribLoader(path=get_grib_path('sr', step)) for step in steps]

            #Compute the 6 hourly fields
            # [TODO] - Should be dynamic
            yield log.info(
                'Computing the required parameters '
                '(FER, cpr, tp, wspd700, cape, sr).'
            )
            TP = compute_accumulated_field(tp1, tp2) * 1000
            CP = compute_accumulated_field(cp1, cp2) * 1000
            U700 = compute_weighted_average_field(u1, u2)
            V700 = compute_weighted_average_field(v1, v2)
            WSPD = compute_rms_field(U700, V700)
            CAPE = compute_weighted_average_field(cape1, cape2)
            SR = compute_accumulated_field(sr1) / 86400

            #Select the nearest grid-point from the rainfall observations
            yield log.info(
                'Selecting the nearest grid point to rainfall observations.'
            )
            TP_Ob = TP.nearest_gridpoint(obs)  # Geopoints(list) instance

            #Select only the values that correspond to TP>=1
            yield log.info(
                'Selecting values that correspond to '
                'tp >= 1 mm/{}h.'.format(Acc)
            )
            TP_Ob1 = Geopoints(
                TP_geopoint
                for TP_geopoint in TP_Ob
                if TP_geopoint.value >= 1
            )
            if not TP_Ob1:
                yield log.warn('No values of tp >= 1 mm/{}h.'.format(Acc))
                continue

            yield log.success('Write data to: {}'.format(PathOUT))

            CP_Ob = CP.nearest_gridpoint(obs)
            WSPD_Ob = WSPD.nearest_gridpoint(obs)
            CAPE_Ob = CAPE.nearest_gridpoint(obs)
            SR_Ob = SR.nearest_gridpoint(obs)

            CP_Ob1 = Geopoints(
                CP_geopoint
                for CP_geopoint, TP_geopoint in zip(CP_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            WSPD_Ob1 = Geopoints(
                WSPD_geopoint
                for WSPD_geopoint, TP_geopoint in zip(WSPD_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            CAPE_Ob1 = Geopoints(
                CAPE_geopoint
                for CAPE_geopoint, TP_geopoint in zip(CAPE_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            SR_Ob1 = Geopoints(
                SR_geopoint
                for SR_geopoint, TP_geopoint in zip(SR_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            # Compute other parameters
            obs1 = Geopoints(
                obs_geopoint
                for obs_geopoint, TP_geopoint in zip(obs.geopoints, TP_Ob)
                if TP_geopoint.value >= 1
            )

            latObs_1 = obs1.latitudes
            lonObs_1 = obs1.longitudes
            CPr = CP_Ob1 / TP_Ob1
            FER = (obs1 - TP_Ob1) / TP_Ob1

            # Compute the Local Solar Time
            # Select values at the right of the Greenwich Meridian
            temp_lonPos = lonObs_1 * (lonObs_1 >= 0)
            # Compute the time difference between the local place and the Greenwich Meridian
            lstPos = HourVF_num + (temp_lonPos/15.0)
            # Put back to zero the values that are not part of the subset (lonObs_1 >= 0)
            lstPos = lstPos * (temp_lonPos != 0)
            # Adjust the times that appear bigger than 24 (the time relates to the following day)
            temp_lstPosMore24 = (lstPos * (lstPos >= 24)) - 24
            temp_lstPosMore24 = temp_lstPosMore24 * (temp_lstPosMore24 > 0)
            # Restore the dataset
            tempPos = lstPos * (lstPos < 24) + temp_lstPosMore24
            # Select values at the left of the Greenwich Meridian
            temp_lonNeg = lonObs_1 * (lonObs_1 < 0)
            # Compute the time difference between the local place and the Greenwich Meridian
            lstNeg = HourVF_num - abs((temp_lonNeg/15.0))
            # Put back to zero the values that are not part of the subset (lonObs_1 < 0)
            lstNeg = lstNeg * (temp_lonNeg != 0)
            # Adjust the times that appear smaller than 24 (the time relates to the previous day)
            temp_lstNegLess0 = lstNeg * (lstNeg < 0) + 24
            temp_lstNegLess0 = temp_lstNegLess0 * (temp_lstNegLess0 != 24)
            # Restore the dataset
            tempNeg = lstNeg * (lstNeg >0) + temp_lstNegLess0
            # Combine both subsets
            vals_LST = numpy.concatenate(tempPos, tempNeg)

            #Saving the outpudt file in ascii format
            vals_TP = TP_Ob1.values
            vals_CP = CP_Ob1.values
            vals_OB = obs1.values
            vals_FER = FER.values
            vals_CPr = CPr.values
            vals_WSPD = WSPD_Ob1.values
            vals_CAPE = CAPE_Ob1.values
            vals_SR = SR_Ob1.values

            n = len(vals_FER)
            obsUSED = obsUSED + n
            for i in range(n):
                data = map(str, [DateVF, HourVF, vals_OB[i], latObs_1[i], lonObs_1[i], vals_FER[i], vals_CPr[i], vals_TP[i], vals_WSPD[i], vals_CAPE[i], vals_SR[i], vals_LST[i]])
                Output_file.write('\t'.join(data) + '\n')

        #12 hourly Accumulation
        elif Acc == 12:
            steps = [leadstart + step for step in generate_steps(Acc)]

            step1 = leadstart
            step2 = leadstart + (Acc/2)
            step3 = leadstart + Acc

            # Defining the parameters for the rainfall observations
            validDateF = (
                datetime.combine(curr_date, datetime.min.time()) +
                timedelta(hours=curr_time) +
                timedelta(hours=steps[-1])
            )
            DateVF = validDateF.strftime('%Y%m%d')
            HourVF = validDateF.strftime('%H')
            yield log.info('RAINFALL OBS PARAMETERS')
            yield log.info(
                'Validity date/time (end of {} hourly '
                'period) = {}'.format(Acc, validDateF)
            )

            #Looking for no repetions in the computed dates and times
            if validDateF in counterValidTimes:
                yield log.warn('Valid Date and Time already computed.')
                continue

            counterValidTimes.append(validDateF)
            dirOBS = os.path.join(PathOBS, AccSTR, DateVF)
            fileOBS = 'tp_{:02d}_{}_{}.geo'.format(Acc, DateVF, HourVF)

            obs_path = os.path.join(dirOBS, fileOBS)
            if not os.path.exists(obs_path):
                yield log.warn('File not found in DB: {}.'.format(obs_path))
                continue

            # Reading Rainfall Observations
            yield log.info('Read rainfall observation: '.format(obs_path))
            obs=GeopointsLoader(path=obs_path)
            nOBS = len(obs.values)

            if nOBS == 1:
                #which will account for the cases of zero obeservation in the geopoint file (because the length of the vector will be forced to 1),
                #or cases in which there is only one observation in the geopoint file
                yield log.warn('No rainfall observations: {}.'.format(fileOBS))
                continue

            obsTOT = obsTOT + nOBS
            if step3 <= 24:
                step1sr = 1
                step3sr = 25  # [XXX]
            else:
                step1sr = step3 - 24
                step3sr = step3

            #Reading forecasts
            yield log.info('Read forecast data')
            tp1, tp2, tp3 = [GribLoader(path=get_grib_path('tp', step)) for step in steps]
            cp1, cp2, cp3 = [GribLoader(path=get_grib_path('cp', step)) for step in steps]
            u1, u2, u3 = [GribLoader(path=get_grib_path('u700', step)) for step in steps]
            v1, v2, v3 = [GribLoader(path=get_grib_path('v700', step)) for step in steps]
            cape1, cape2, cape3 = [GribLoader(path=get_grib_path('cape', step)) for step in steps]
            sr1, sr2, sr3 = [GribLoader(path=get_grib_path('sr', step)) for step in steps]

            #Compute the 12 hourly fields
            # [TODO] - Should be dynamic
            yield log.info(
                'Computing the required parameters '
                '(FER, cpr, tp, wspd700, cape, sr).'
            )
            TP = compute_accumulated_field(tp1, tp2, tp3) * 1000
            CP = compute_accumulated_field(cp1, cp2, cp3) * 1000
            U700 = compute_weighted_average_field(u1, u2, u3)
            V700 = compute_weighted_average_field(v1, v2, v3)
            WSPD = compute_rms_field(U700, V700)
            CAPE = compute_weighted_average_field(cape1, cape2, cape3)
            SR = compute_accumulated_field(sr1, sr3) / 86400

            #Select the nearest grid-point from the rainfall observations
            yield log.info(
                'Selecting the nearest grid point to rainfall observations.'
            )
            TP_Ob = TP.nearest_gridpoint(obs)

            #Select only the values that correspond to TP>=1
            yield log.info(
                'Selecting values that correspond to '
                'tp >= 1 mm/{}h.'.format(Acc)
            )
            TP_Ob1 = Geopoints(
                TP_geopoint
                for TP_geopoint in TP_Ob
                if TP_geopoint.value >= 1
            )
            if not TP_Ob1:
                yield log.warn('No values of tp >= 1 mm/{}h.'.format(Acc))
                continue

            CP_Ob = CP.nearest_gridpoint(obs)
            WSPD_Ob = WSPD.nearest_gridpoint(obs)
            CAPE_Ob = CAPE.nearest_gridpoint(obs)
            SR_Ob = SR.nearest_gridpoint(obs)

            yield log.success('Write data to: {}'.format(PathOUT))
            CP_Ob1 = Geopoints(
                CP_geopoint
                for CP_geopoint, TP_geopoint in zip(CP_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            WSPD_Ob1 = Geopoints(
                WSPD_geopoint
                for WSPD_geopoint, TP_geopoint in zip(WSPD_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            CAPE_Ob1 = Geopoints(
                CAPE_geopoint
                for CAPE_geopoint, TP_geopoint in zip(CAPE_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            SR_Ob1 = Geopoints(
                SR_geopoint
                for SR_geopoint, TP_geopoint in zip(SR_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            # Compute other parameters
            obs1 = Geopoints(
                obs_geopoint
                for obs_geopoint, TP_geopoint in zip(obs.geopoints, TP_Ob)
                if TP_geopoint.value >= 1
            )
            latObs_1 = obs1.latitudes
            lonObs_1 = obs1.longitudes
            CPr = CP_Ob1 / TP_Ob1
            FER = (obs1 - TP_Ob1) / TP_Ob1

            #Saving the output file in ascii format
            vals_TP = TP_Ob1.values
            vals_CP = CP_Ob1.values
            vals_OB = obs1.values
            vals_FER = FER.values
            vals_CPr = CPr.values
            vals_WSPD = WSPD_Ob1.values
            vals_CAPE = CAPE_Ob1.values
            vals_SR = SR_Ob1.values

            n = len(vals_FER)
            obsUSED += n
            for i in range(n):
                data = map(str, [DateVF, HourVF, vals_OB[i], latObs_1[i], lonObs_1[i], vals_FER[i], vals_CPr[i], vals_TP[i], vals_WSPD[i], vals_CAPE[i], vals_SR[i], 'NaN'])
                Output_file.write('\t'.join(data) + '\n')

        #24 hourly Accumulation
        elif Acc == 24:
            steps = [leadstart + step for step in generate_steps(Acc)]

            # Defining the parameters for the rainfall observations
            validDateF = (
                    datetime.combine(curr_date, datetime.min.time()) +
                    timedelta(hours=curr_time) +
                    timedelta(hours=steps[-1])
            )
            DateVF = validDateF.strftime('%Y%m%d')
            HourVF = validDateF.strftime('%H')
            yield log.info('RAINFALL OBS PARAMETERS')
            yield log.info(
                'Validity date/time (end of {} hourly '
                'period) = {}'.format(Acc, validDateF)
            )

            #Looking for no repetions in the computed dates and times
            if validDateF in counterValidTimes:
                yield log.warn('Valid Date and Time already computed.')
                continue
            counterValidTimes.append(validDateF)
            dirOBS = os.path.join(PathOBS, AccSTR, DateVF)
            fileOBS = 'tp_{:02d}_{}_{}.geo'.format(Acc, DateVF, HourVF)

            obs_path = os.path.join(dirOBS, fileOBS)
            if not os.path.exists(obs_path):
                yield log.warn('File not found in DB: {}.'.format(obs_path))
                continue

            #Reading Rainfall Observations
            yield log.info('Read rainfall observation: '.format(obs_path))
            obs=GeopointsLoader(path=obs_path)
            nOBS = len(obs.values)

            if nOBS == 1:
                # which will account for the cases of zero obeservation in the geopoint file (because the length of the vector will be forced to 1),
                # or cases in which there is only one observation in the geopoint file
                yield log.warn('No rainfall observations: {}.'.format(fileOBS))
                continue

            #Reading Forecasts
            obsTOT += nOBS
            yield log.info('Read forecast data')
            tp1, tp2, tp3, tp4, tp5 = [GribLoader(path=get_grib_path('tp', step)) for step in steps]
            cp1, cp2, cp3, cp4, cp5 = [GribLoader(path=get_grib_path('cp', step)) for step in steps]
            u1, u2, u3, u4, u5 = [GribLoader(path=get_grib_path('u700', step)) for step in steps]
            v1, v2, v3, v4, v5 = [GribLoader(path=get_grib_path('v700', step)) for step in steps]
            cape1, cape2, cape3, cape4, cape5 = [GribLoader(path=get_grib_path('cape', step)) for step in steps]
            sr1, sr2, sr3, sr4, sr5 = [GribLoader(path=get_grib_path('sr', step)) for step in steps]

            #Compute the 24 hourly fields
            # [TODO] - Should be dynamic
            yield log.info(
                'Computing the required parameters '
                '(FER, cpr, tp, wspd700, cape, sr).'
            )
            TP = compute_accumulated_field(tp1, tp2, tp3, tp4, tp5) * 1000
            CP = compute_accumulated_field(cp1, cp2, cp3, cp4, cp5) * 1000
            U700 = compute_weighted_average_field(u1, u2, u3, u4, u5)
            V700 = compute_weighted_average_field(v1, v2, v3, v4, v5)
            WSPD = compute_rms_field(U700, V700)
            CAPE = compute_weighted_average_field(cape1, cape2, cape3, cape4, cape5)
            SR = compute_accumulated_field(sr1, sr2, sr3, sr4, sr5) / 86400

            #Select the nearest grid-point from the rainfall observations
            yield log.info(
                'Selecting the nearest grid point to rainfall observations.'
            )
            TP_Ob = TP.nearest_gridpoint(obs)

            #Select only the values that correspond to TP>=1
            yield log.info(
                'Selecting values that correspond to '
                'tp >= 1 mm/{}h.'.format(Acc)
            )
            TP_Ob1 = Geopoints(
                TP_geopoint
                for TP_geopoint in TP_Ob
                if TP_geopoint.value >= 1
            )
            if not TP_Ob1:
                yield log.warn('No values of tp >= 1 mm/{}h.'.format(Acc))
                continue

            CP_Ob = CP.nearest_gridpoint(obs)
            WSPD_Ob = WSPD.nearest_gridpoint(obs)
            CAPE_Ob = CAPE.nearest_gridpoint(obs)
            SR_Ob = SR.nearest_gridpoint(obs)

            yield log.success('Write data to: {}'.format(PathOUT))
            CP_Ob1 = Geopoints(
                CP_geopoint
                for CP_geopoint, TP_geopoint in zip(CP_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            WSPD_Ob1 = Geopoints(
                WSPD_geopoint
                for WSPD_geopoint, TP_geopoint in zip(WSPD_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            CAPE_Ob1 = Geopoints(
                CAPE_geopoint
                for CAPE_geopoint, TP_geopoint in zip(CAPE_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            SR_Ob1 = Geopoints(
                SR_geopoint
                for SR_geopoint, TP_geopoint in zip(SR_Ob, TP_Ob)
                if TP_geopoint.value >= 1
            )

            # Compute other parameters
            obs1 = Geopoints(
                obs_geopoint
                for obs_geopoint, TP_geopoint in zip(obs.geopoints, TP_Ob)
                if TP_geopoint.value >= 1
            )
            latObs_1 = obs1.latitudes
            lonObs_1 = obs1.longitudes
            CPr = CP_Ob1 / TP_Ob1
            FER = (obs1 - TP_Ob1) / TP_Ob1

            #Saving the output file in ascii format
            vals_TP = TP_Ob1.values
            vals_CP = CP_Ob1.values
            vals_OB = obs1.values
            vals_FER = FER.values
            vals_CPr = CPr.values
            vals_WSPD = WSPD_Ob1.values
            vals_CAPE = CAPE_Ob1.values
            vals_SR = SR_Ob1.values

            n = len(vals_FER)
            obsUSED += n
            for i in range(n):
                data = map(str, [DateVF, HourVF, vals_OB[i], latObs_1[i], lonObs_1[i], vals_FER[i], vals_CPr[i], vals_TP[i], vals_WSPD[i], vals_CAPE[i], vals_SR[i], 'NaN'])
                Output_file.write('\t'.join(data) + '\n')

        yield log.info('\n' + '*'*80)

    yield log.success(
        'Number of observations in the whole training period: '.format(obsTOT)
    )
    yield log.success(
        'Number of observations actually used in the training period '
        '(tp >= 1 mm/{}h): {}'.format(Acc, obsUSED)
    )

    Output_file.write('\nNumber of observations in the whole training period: {}\n'.format(obsTOT))
    Output_file.write('Number of observations actually used in the training period (that correspond to tp >= 1 mm/{0}h): {1}'.format(Acc, obsUSED))
    Output_file.close()