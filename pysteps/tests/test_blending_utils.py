# -*- coding: utf-8 -*-

import os

import numpy as np
from numpy.testing import assert_array_almost_equal
import pytest

import pysteps
from pysteps.blending.utils import (
    stack_cascades,
    blend_cascades,
    recompose_cascade,
    blend_optical_flows,
    decompose_NWP,
    compute_store_nwp_motion,
    load_NWP,
)

# TODO: Fix tests for xarray fields

pytest.importorskip("netCDF4")

# Read an NWP forecast
root_path = pysteps.rcparams.data_sources["rmi_nwp"]["root_path"]
rel_path = os.path.join("2021", "07", "04")
filename = os.path.join(root_path, rel_path, "ao13_2021070412_native_5min.nc")
precip_nwp = pysteps.io.import_rmi_nwp_xr(filename)[0:7]

nwp_metadata = precip_nwp.x.attrs.copy()
nwp_metadata.update(**precip_nwp.y.attrs)
nwp_metadata.update(**precip_nwp.attrs)

# Get the analysis time and valid time
times_nwp = precip_nwp["t"].values

# Prepare input NWP files
# Convert to rain rates [mm/h]
converter = pysteps.utils.get_method("mm/h")
precip_nwp, nwp_metadata = converter(precip_nwp, nwp_metadata)

# Threshold the data
precip_nwp.data[precip_nwp.data < 0.1] = 0.0
nwp_metadata["threshold"] = 0.1

# Transform the data
transformer = pysteps.utils.get_method("dB")
precip_nwp, nwp_metadata = transformer(
    precip_nwp.values, nwp_metadata, threshold=nwp_metadata["threshold"]
)

# Set two issue times for testing
issue_time_first = times_nwp[0]
issue_time_second = times_nwp[3]

# Set the blending weights (we'll blend with a 50-50 weight)
weights = np.full((2, 8), fill_value=0.5)

# Set the testing arguments
# Test function arguments
utils_arg_names = (
    "precip_nwp",
    "nwp_model",
    "issue_times",
    "timestep",
    "n_timesteps",
    "valid_times",
    "shape",
    "weights",
)

# Test function values
utils_arg_values = [
    (
        precip_nwp,
        "test",
        [issue_time_first, issue_time_second],
        5.0,
        3,
        times_nwp,
        precip_nwp.shape[1:],
        weights,
    )
]


###
# The test
###
@pytest.mark.parametrize(utils_arg_names, utils_arg_values)

# The test function to be used
def test_blending_utils(
    precip_nwp,
    nwp_model,
    issue_times,
    timestep,
    n_timesteps,
    valid_times,
    shape,
    weights,
):
    """Tests if all blending utils functions behave correctly."""

    # First, make the output path if it does not exist yet
    tmpdir = "./tmp/"
    os.makedirs(tmpdir, exist_ok=True)

    # Get the optical flow method
    oflow_method = pysteps.motion.get_method("lucaskanade")

    ###
    # Compute and store the motion
    ###
    compute_store_nwp_motion(
        precip_nwp=precip_nwp,
        oflow_method=oflow_method,
        analysis_time=valid_times[0],
        nwp_model=nwp_model,
        output_path=tmpdir,
    )

    # Check if file exists
    date_string = np.datetime_as_string(valid_times[0], "s")
    motion_file = os.path.join(
        tmpdir,
        nwp_model
        + "_"
        + date_string[:4]
        + date_string[5:7]
        + date_string[8:10]
        + date_string[11:13]
        + date_string[14:16]
        + date_string[17:19]
        + ".npy",
    )
    assert os.path.exists(motion_file)

    ###
    # Decompose and store NWP forecast
    ###
    decompose_NWP(
        R_NWP=precip_nwp,
        NWP_model=nwp_model,
        analysis_time=valid_times[0],
        timestep=timestep,
        valid_times=valid_times,
        num_cascade_levels=8,
        num_workers=1,
        output_path=tmpdir,
        decomp_method="fft",
        fft_method="numpy",
        domain="spatial",
        normalize=True,
        compute_stats=True,
        compact_output=False,
    )

    # Check if file exists
    decomp_file = os.path.join(
        tmpdir,
        "cascade_"
        + nwp_model
        + "_"
        + date_string[:4]
        + date_string[5:7]
        + date_string[8:10]
        + date_string[11:13]
        + date_string[14:16]
        + date_string[17:19]
        + ".nc",
    )
    assert os.path.exists(decomp_file)

    ###
    # Now check if files load correctly for two different issue times
    ###
    precip_decomposed_nwp_first, v_nwp_first = load_NWP(
        input_nc_path_decomp=os.path.join(decomp_file),
        input_path_velocities=os.path.join(motion_file),
        start_time=issue_times[0],
        n_timesteps=n_timesteps,
    )

    precip_decomposed_nwp_second, v_nwp_second = load_NWP(
        input_nc_path_decomp=os.path.join(decomp_file),
        input_path_velocities=os.path.join(motion_file),
        start_time=issue_times[1],
        n_timesteps=n_timesteps,
    )

    # Check if the output type and shapes are correct
    assert isinstance(precip_decomposed_nwp_first, list)
    assert isinstance(precip_decomposed_nwp_second, list)
    assert isinstance(precip_decomposed_nwp_first[0], dict)
    assert isinstance(precip_decomposed_nwp_second[0], dict)

    assert "domain" in precip_decomposed_nwp_first[0]
    assert "normalized" in precip_decomposed_nwp_first[0]
    assert "compact_output" in precip_decomposed_nwp_first[0]
    assert "valid_times" in precip_decomposed_nwp_first[0]
    assert "cascade_levels" in precip_decomposed_nwp_first[0]
    assert "means" in precip_decomposed_nwp_first[0]
    assert "stds" in precip_decomposed_nwp_first[0]

    assert precip_decomposed_nwp_first[0]["cascade_levels"].shape == (
        8,
        shape[0],
        shape[1],
    )
    assert precip_decomposed_nwp_first[0]["domain"] == "spatial"
    assert precip_decomposed_nwp_first[0]["normalized"] == True
    assert precip_decomposed_nwp_first[0]["compact_output"] == False
    assert len(precip_decomposed_nwp_first) == n_timesteps + 1
    assert len(precip_decomposed_nwp_second) == n_timesteps + 1
    assert precip_decomposed_nwp_first[0]["means"].shape[0] == 8
    assert precip_decomposed_nwp_first[0]["stds"].shape[0] == 8

    assert np.array(v_nwp_first).shape == (n_timesteps + 1, 2, shape[0], shape[1])
    assert np.array(v_nwp_second).shape == (n_timesteps + 1, 2, shape[0], shape[1])

    # Check if the right times are loaded
    assert (
        precip_decomposed_nwp_first[0]["valid_times"][0] == valid_times[0]
    ), "Not the right valid times were loaded for the first forecast"
    assert (
        precip_decomposed_nwp_second[0]["valid_times"][0] == valid_times[3]
    ), "Not the right valid times were loaded for the second forecast"

    # Check, for a sample, if the stored motion fields are as expected
    assert_array_almost_equal(
        v_nwp_first[1],
        oflow_method(precip_nwp[0:2, :, :]),
        decimal=3,
        err_msg="Stored motion field of first forecast not equal to expected motion field",
    )
    assert_array_almost_equal(
        v_nwp_second[1],
        oflow_method(precip_nwp[3:5, :, :]),
        decimal=3,
        err_msg="Stored motion field of second forecast not equal to expected motion field",
    )

    ###
    # Stack the cascades
    ###
    precip_decomposed_first_stack, mu_first_stack, sigma_first_stack = stack_cascades(
        R_d=precip_decomposed_nwp_first, donorm=False
    )

    print(precip_decomposed_nwp_first)
    print(precip_decomposed_first_stack)
    print(mu_first_stack)

    (
        precip_decomposed_second_stack,
        mu_second_stack,
        sigma_second_stack,
    ) = stack_cascades(R_d=precip_decomposed_nwp_second, donorm=False)

    # Check if the array shapes are still correct
    assert precip_decomposed_first_stack.shape == (
        n_timesteps + 1,
        8,
        shape[0],
        shape[1],
    )
    assert mu_first_stack.shape == (n_timesteps + 1, 8)
    assert sigma_first_stack.shape == (n_timesteps + 1, 8)

    ###
    # Blend the cascades
    ###
    precip_decomposed_blended = blend_cascades(
        cascades_norm=np.stack(
            (precip_decomposed_first_stack[0], precip_decomposed_second_stack[0])
        ),
        weights=weights,
    )

    assert precip_decomposed_blended.shape == precip_decomposed_first_stack[0].shape

    ###
    # Blend the optical flow fields
    ###
    v_nwp_blended = blend_optical_flows(
        flows=np.stack((v_nwp_first[1], v_nwp_second[1])), weights=weights[:, 1]
    )

    assert v_nwp_blended.shape == v_nwp_first[1].shape
    assert_array_almost_equal(
        v_nwp_blended,
        (oflow_method(precip_nwp[0:2, :, :]) + oflow_method(precip_nwp[3:5, :, :])) / 2,
        decimal=3,
        err_msg="Blended motion field does not equal average of the two motion fields",
    )

    ###
    # Recompose the fields (the non-blended fields are used for this here)
    ###
    precip_recomposed_first = recompose_cascade(
        combined_cascade=precip_decomposed_first_stack[0],
        combined_mean=mu_first_stack[0],
        combined_sigma=sigma_first_stack[0],
    )
    precip_recomposed_second = recompose_cascade(
        combined_cascade=precip_decomposed_second_stack[0],
        combined_mean=mu_second_stack[0],
        combined_sigma=sigma_second_stack[0],
    )

    assert_array_almost_equal(
        precip_recomposed_first,
        precip_nwp[0, :, :],
        decimal=3,
        err_msg="Recomposed field of first forecast does not equal original field",
    )
    assert_array_almost_equal(
        precip_recomposed_second,
        precip_nwp[3, :, :],
        decimal=3,
        err_msg="Recomposed field of second forecast does not equal original field",
    )
