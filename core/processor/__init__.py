import os
from datetime import datetime, timedelta
from textwrap import dedent

from core.loaders.ascii import ASCIIEncoder
from core.loaders.fieldset import Fieldset
from core.loaders.geopoints import Geopoints

from ..computations.models import Computer
from .log_factory import (
    general_parameters_logs,
    observations_logs,
    output_file_logs,
    predictand_logs,
    predictors_logs,
)
from .utils import (
    adjust_steps,
    compute_local_solar_time,
    generate_steps,
    iter_daterange,
    log,
)


def run(config):
    BaseDateS = config.parameters.date_start
    BaseDateF = config.parameters.date_end
    Acc = config.predictand.accumulation
    LimSU = config.parameters.limit_spin_up
    PathOBS = config.observations.path
    PathFC = config.predictors.path
    PathPredictand = config.predictand.path
    PathOUT = config.parameters.out_path

    # Set up the input/output parameters
    BaseDateS = datetime.strptime(BaseDateS, "%Y%m%d").date()
    BaseDateF = datetime.strptime(BaseDateF, "%Y%m%d").date()
    BaseDateSSTR = BaseDateS.strftime("%Y%m%d")
    BaseDateFSTR = BaseDateF.strftime("%Y%m%d")
    AccSTR = f"Acc{Acc:02}h"

    computations = config.computations

    serializer = ASCIIEncoder(path=PathOUT)

    header = dedent(
        f"""
        # THIS IS AN AUTOGENERATED FILE. DO NOT EDIT THIS FILE DIRECTLY.
        #
        # Created on {datetime.now()}.
        #
        # """  # Do NOT strip
    )

    header += "\n# ".join(general_parameters_logs(config, raw=True)) + "\n# "
    header += "\n# ".join(predictand_logs(config, raw=True)) + "\n# "
    header += "\n# ".join(predictors_logs(config, raw=True)) + "\n# "
    header += "\n# ".join(observations_logs(config, raw=True)) + "\n# "
    header += "\n# ".join(output_file_logs(config, raw=True))

    serializer.header = header.strip()

    #############################################################################################

    # PROCESSING MODEL DATA

    yield log.bold("************************************")
    yield log.bold("ecPoint-Calibrate - POINT DATA TABLE")
    yield log.bold("************************************")

    yield from general_parameters_logs(config)
    yield from predictand_logs(config)
    yield from predictors_logs(config)
    yield from observations_logs(config)
    yield from output_file_logs(config)

    yield log.info("")
    yield log.bold("*** START COMPUTATIONS ***")

    # Counter for the BaseDate and BaseTime to avoid repeating the same forecasts in different cases
    counter_used_FC = {}
    obsTOT = 0
    obsUSED = 0
    DiscBT = config.observations.discretization
    BaseTimeS = config.observations.start_time

    for curr_date, curr_time, step_s, case in iter_daterange(
        start=BaseDateS, end=BaseDateF, start_hour=BaseTimeS, interval=DiscBT
    ):
        yield log.info("")
        if case != 1:
            yield log.bold("**********")
        yield log.bold(f"Case {case}")
        yield log.bold("FORECAST PARAMETERS:")

        step_f = step_s + Acc
        yield log.info(
            f'  {curr_date.strftime("%Y%m%d")}, {curr_time:02d} UTC, (t+{step_s}, t+{step_f})'
        )
        yield log.info("")

        new_curr_date, new_curr_time, new_step_s, msgs = adjust_steps(
            date=curr_date,
            hour=curr_time,
            step=step_s,
            start_hour=BaseTimeS,
            limSU=LimSU,
            interval=DiscBT,
        )

        for msg in msgs:
            yield log.info(msg)

        new_step_f = new_step_s + Acc

        new_curr_date_str = new_curr_date.strftime("%Y%m%d")
        new_curr_time_str = f"{new_curr_time:02d}"

        used_forecast = f"{new_curr_date_str}, {new_curr_time_str} UTC, (t+{new_step_s}, t+{new_step_f})"
        if used_forecast in counter_used_FC:
            log.warn(
                f"  The above forecast was already considered for computation in Case {counter_used_FC[used_forecast]}"
            )
            continue

        # Reading the forecasts
        if new_curr_date < BaseDateS or new_curr_date > BaseDateF:
            log.warn(
                f"  Forecast out of the calibration period {BaseDateSSTR} - {BaseDateFSTR}. Forecast not considered."
            )
            continue

        counter_used_FC[used_forecast] = case
        yield log.info(f"  {used_forecast}")
        yield log.info("")

        def get_grib_path(predictand, step):
            return os.path.join(
                PathFC,
                predictand,
                new_curr_date_str + new_curr_time_str,
                "_".join(
                    [predictand, new_curr_date_str, new_curr_time_str, f"{step:02d}"]
                )
                + ".grib",
            )

        # Note about the computation of the sr.
        # The solar radiation is a cumulative variable and its units is J/m2 (which means, W*s/m2).
        # One wants the 24h. The 24h mean is obtained by taking the difference between the beginning and the end of the 24 hourly period
        # and dividing by the number of seconds in that period (24h = 86400 sec). Thus, the unit will be W/m2

        steps = [new_step_s + step for step in generate_steps(Acc)]

        # Defining the parameters for the rainfall observations
        validDateF = (
            datetime.combine(new_curr_date, datetime.min.time())
            + timedelta(hours=new_curr_time)
            + timedelta(hours=new_step_f)
        )
        DateVF = validDateF.strftime("%Y%m%d")
        HourVF = validDateF.strftime("%H")
        HourVF_num = validDateF.hour
        yield log.bold("OBSERVATIONS PARAMETERS:")
        yield log.info(f"  Validity date/time (end of {Acc}h period) = {validDateF}")

        dirOBS = os.path.join(PathOBS, AccSTR, DateVF)
        fileOBS = f"tp_{Acc:02d}_{DateVF}_{HourVF}.geo"

        obs_path = os.path.join(dirOBS, fileOBS)

        # Reading Rainfall Observations
        yield log.info(f"  Read observation file: {os.path.basename(obs_path)}")
        try:
            obs = Geopoints.from_path(path=obs_path)
        except IOError:
            yield log.warn(f"  Observation file not found in DB: {obs_path}.")
            continue
        except Exception:
            yield log.error(
                f"  Error reading observation file: {os.path.basename(obs_path)}"
            )
            continue

        nOBS = len(obs.dataframe)

        if nOBS == 0:
            yield log.warn(
                f"  No observation in the file: {os.path.basename(obs_path)}. Forecast not considered."
            )
            continue

        obsTOT += nOBS

        if Acc == 24:
            step_start_sr, step_end_sr = steps[0], steps[-1]
        else:
            if steps[-1] <= 24:
                step_start_sr, step_end_sr = 0, 24
            else:
                step_start_sr, step_end_sr = steps[-1] - 24, steps[-1]

        yield log.info("")
        yield log.bold("PREDICTORS COMPUTATIONS:")

        for computation in computations:
            computation.is_reference = (
                len(computation.inputs) == 1
                and computation.inputs[0] == config.predictand.code
            )

        base_fields = set(config.predictors.codes)

        derived_computations = [
            computation
            for computation in computations
            if set(computation.inputs) - base_fields != set()
        ]

        base_computations = sorted(
            [
                computation
                for computation in computations
                if computation not in derived_computations
            ],
            key=lambda computation: computation.is_reference,
            reverse=True,
        )

        computations_cache = {}
        computations_result = []
        skip = False

        for computation in base_computations:
            computer = Computer(computation)
            predictor_code = computer.computation.inputs[0]

            steps = (
                [step_start_sr, step_end_sr]
                if computation.field == "24H_SOLAR_RADIATION"
                else steps
            )

            try:
                computation_steps = [
                    Fieldset.from_path(path=get_grib_path(predictor_code, step))
                    for step in steps
                ]
            except (IOError, Exception):
                skip = True
                break

            computed_value = computer.run(*computation_steps)

            computations_cache[computation.shortname] = computed_value

            if not computation.is_reference and not computation.isPostProcessed:
                continue

            yield log.info("  Selecting the nearest grid point to observations.")
            geopoints = computed_value.nearest_gridpoint(obs)

            # Select only the values that correspond to TP>=1
            if computation.is_reference:
                reference_predictor = computation.shortname
                ref_geopoints = geopoints
                mask = ref_geopoints.values >= 1

                yield log.info(
                    f"  Selecting values that correspond to {computation.shortname}"
                    f" >= {config.predictand.min_value} mm/{Acc}h."
                )

                ref_geopoints_filtered_df = ref_geopoints.dataframe[mask]

                if ref_geopoints_filtered_df.empty:
                    yield log.warn(
                        f"  No values of {computation.shortname} >= 1 mm/{Acc}h."
                    )
                    skip = True
                    break
                elif computation.isPostProcessed:
                    computations_result.append(
                        (computation.shortname, ref_geopoints_filtered_df["value"])
                    )
            else:
                geopoints_filtered_df = geopoints.dataframe[mask]

                computations_result.append(
                    (computation.shortname, geopoints_filtered_df["value"])
                )

        if skip:
            continue

        derived_computations = [
            computation
            for computation in derived_computations
            if computation.isPostProcessed
        ]

        for computation in derived_computations:
            computer = Computer(computation)
            steps = [
                computations_cache[field_input] for field_input in computation.inputs
            ]

            if computation.field == "RATIO_FIELD":
                dividend = steps[0]
                # [TODO] Cache the following in the computations_cache
                geopoints = dividend.nearest_gridpoint(obs)
                geopoints_filtered_df = geopoints.dataframe[mask]

                computed_value = computer.run(
                    geopoints_filtered_df["value"], ref_geopoints_filtered_df["value"]
                )
                computations_result.append((computation.shortname, computed_value))
            else:
                computed_value = computer.run(*steps)
                geopoints = computed_value.nearest_gridpoint(obs)
                geopoints_filtered_df = geopoints.dataframe[mask]
                computations_result.append(
                    (computation.shortname, geopoints_filtered_df["value"])
                )

        # Compute other parameters
        obs1 = obs.dataframe[mask]

        latObs_1 = obs1["latitude"]
        lonObs_1 = obs1["longitude"]
        # [XXX] CPr = CP_Ob1 / TP_Ob1

        vals_errors = []

        yield log.info("")
        yield log.info(f"  Computing the {config.predictand.error}.")
        if config.predictand.error == "FER":
            FER = (
                obs1["value"] - ref_geopoints_filtered_df["value"]
            ) / ref_geopoints_filtered_df["value"]
            vals_errors.append(("FER", FER))

        if config.predictand.error == "FE":
            FE = obs1["value"] - ref_geopoints_filtered_df["value"]
            vals_errors.append(("FE", FE))

        vals_LST = compute_local_solar_time(longitudes=lonObs_1, hour=HourVF_num)

        # Saving the output file in ascii format
        vals_OB = obs1["value"]

        n = len(vals_OB)
        obsUSED = obsUSED + n
        yield log.info("")
        yield log.bold("POINT DATA TABLE:")
        yield log.info(f"  Saving the point data table to output file: {PathOUT}")

        columns = (
            [
                ("Date", [DateVF] * n),
                ("TimeUTC", [HourVF] * n),
                ("OBS", vals_OB),
                ("latOBS", latObs_1),
                ("lonOBS", lonObs_1),
                ("LST", vals_LST),
            ]
            + vals_errors
            + computations_result
        )

        serializer.add_columns_chunk(columns)

    yield log.success(
        f"Number of observations in the whole calibration period: {obsTOT}"
    )
    yield log.success(
        f"Number of observations actually used in the calibration period "
        f"(tp >= {config.predictand.min_value} mm/{Acc}h): {obsUSED}"
    )

    footer = dedent(
        f"""
        # Number of observations in the whole calibration period = {obsTOT}
        # Number of observations actually used in the calibration period (corresponding to {reference_predictor} => {config.predictand.min_value}mm/{Acc}h) = {obsUSED}
        """
    ).strip()
    serializer.footer = footer
    serializer.write()
