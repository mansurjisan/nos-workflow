"""ADCIRC physics presets and accessors for the fort.15 writer.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/stofs_2d_global), models/adcirc/adcirc_configuration.py. Kept verbatim
apart from this header and the postponed-annotation import so a fort.15 built
from the same config matches his generator.
"""
from __future__ import annotations

from typing import ClassVar, Optional


class AdcircConfiguration:
    """
    Class to hold the configuration for the ADCIRC model
    """

    # List of available SWAN physics versions
    VALID_SWAN_PHYSICS_VERSIONS: ClassVar = ["gen1", "gen2", "gen3", "gen3-st6"]

    # List of valid turbulence models
    VALID_TURBULENCE_MODELS: ClassVar = ["smagorinsky", "eddy_viscosity"]

    # List of valid wind drag formulas
    VALID_WIND_DRAG_FORMULAS: ClassVar = ["default", "garratt", "powell"]

    # List of valid solvers
    VALID_SOLVERS: ClassVar = ["implicit", "explicit"]

    def __init__(self, model_configuration: dict, time_step: float = 1.0) -> None:
        """
        Constructor for the AdcircConfiguration class
        Args:
            model_configuration: Dictionary containing the model configuration
            time_step: Time step for the model
        """
        self.__solver: str = "implicit"
        self.__friction: str = "quadratic"
        self.__turbulence: str = "smagorinsky"
        self.__smagorinsky_coefficient: float = 0.2
        self.__eddy_viscosity_coefficient: float = 2.0
        self.__coordinate_system: int = 2
        self.__quadratic_friction_coefficient: float = 0.0025
        self.__a00: float = 0.35
        self.__b00: float = 0.30
        self.__c00: float = 0.35
        self.__wind_drag_formula: str = "default"
        self.__wind_drag_limit: float = 0.0025
        self.__bottom_friction_limit: float = 0.0010
        self.__tau0: float = 0.005
        self.__h0: float = 0.1
        self.__velmin: float = 0.01
        self.__hbreak: float = 2.0
        self.__ftheta: float = 10.0
        self.__fgamma: float = 1.3333
        self.__advection: bool = False
        self.__implicit_gravity_wave: bool = False
        self.__use_self_attraction_and_loading: bool = False
        self.__wind_limiter_active: bool = False
        self.__slope_limiter_active: bool = False
        self.__slope_limiter_value: float = 1000000000.0
        self.__use_direct_velmin_calculation: bool = False
        self.__use_hf_calculation: bool = False
        self.__station_partial_wet_fix_active: bool = False
        self.__station_partial_wet_fix_option: int = 0
        self.__swan_max_iterations: int = 20
        self.__swan_convergence_npts: int = 95
        self.__swan_spectral_directions: int = 36
        self.__swan_spectral_frequency_bins: int = 40
        self.__swan_spectral_frequency_minimum: float = 0.031384
        self.__swan_spectral_frequency_maximum: float = 1.420416
        self.__wave_coupling_interval: int = 600
        self.__swan_physics_version: str = "gen3"
        self.__coordinate_rotation_x: Optional[float] = None
        self.__coordinate_rotation_y: Optional[float] = None
        self.__use_full_tip: bool = False
        self.__use_vew1d_wet_perimeter: bool = False
        self.__adcirc_output_dict: dict = {
            "velocity": True,
            "meteorology": True,
            "inundation": False,
            "wave_height": True,
            "wave_peak_period": True,
            "wave_mean_period": True,
            "wave_direction": True,
        }

        self.__update_configuration(model_configuration, time_step)

    def __update_configuration(  # noqa: PLR0915
        self, model_configuration: dict, time_step: float
    ) -> None:
        """
        Updates the model configuration with the values from the model configuration dictionary.

        Args:
            model_configuration: Dictionary containing the model configuration
            time_step: Time step for the model (in seconds)

        Returns:
            None
        """
        config_preset = model_configuration.get("preset", "traditional")
        presets = {
            "traditional": self.set_traditional_preset,
            "pringle": lambda: self.set_pringle_preset(time_step),
            "explicit": self.set_explicit_preset,
            "jjw": self.set_jjw_preset,
        }
        presets.get(config_preset, self.set_traditional_preset)()

        self.__solver = model_configuration.get("solver", self.__solver)
        if self.__solver not in AdcircConfiguration.VALID_SOLVERS:
            msg = (
                f"Invalid solver: {self.__solver}. "
                f"Valid options are: {AdcircConfiguration.VALID_SOLVERS}"
            )
            raise ValueError(msg)

        self.__friction = model_configuration.get("friction", self.__friction)

        self.__turbulence = model_configuration.get("turbulence", self.__turbulence)
        if self.__turbulence not in AdcircConfiguration.VALID_TURBULENCE_MODELS:
            msg = (
                f"Invalid turbulence model: {self.__turbulence}. "
                f"Valid options are: {AdcircConfiguration.VALID_TURBULENCE_MODELS}"
            )
            raise ValueError(msg)

        if self.__turbulence == "smagorinsky":
            self.__smagorinsky_coefficient = model_configuration.get(
                "smagorinsky_coefficient", self.__smagorinsky_coefficient
            )
        elif self.__turbulence == "eddy_viscosity":
            self.__eddy_viscosity_coefficient = model_configuration.get(
                "eddy_viscosity_coefficient", self.__eddy_viscosity_coefficient
            )

        if "time_weighting_coefficients" in model_configuration:
            self.__a00 = model_configuration["time_weighting_coefficients"][0]
            self.__b00 = model_configuration["time_weighting_coefficients"][1]
            self.__c00 = model_configuration["time_weighting_coefficients"][2]
            if self.__a00 + self.__b00 + self.__c00 != 1.0:
                msg = (
                    "Time weighting coefficients must sum to 1.0. "
                    f"Current values: {self.__a00}, {self.__b00}, {self.__c00}"
                )
                raise ValueError(msg)

        self.__quadratic_friction_coefficient = model_configuration.get(
            "quadratic_friction_coefficient", self.__quadratic_friction_coefficient
        )
        self.__tau0 = model_configuration.get("tau0", self.__tau0)
        self.__h0 = model_configuration.get("h0", self.__h0)
        self.__velmin = model_configuration.get("velmin", self.__velmin)
        self.__hbreak = model_configuration.get("hbreak", self.__hbreak)
        self.__ftheta = model_configuration.get("ftheta", self.__ftheta)
        self.__fgamma = model_configuration.get("fgamma", self.__fgamma)
        self.__wind_drag_formula = model_configuration.get(
            "wind_drag_formula", self.__wind_drag_formula
        )
        if self.__wind_drag_formula not in AdcircConfiguration.VALID_WIND_DRAG_FORMULAS:
            msg = (
                f"Invalid wind drag formula: {self.__wind_drag_formula}. "
                f"Valid options are: {AdcircConfiguration.VALID_WIND_DRAG_FORMULAS}"
            )
            raise ValueError(msg)

        self.__wind_drag_limit = model_configuration.get(
            "wind_drag_limit", self.__wind_drag_limit
        )
        if self.__wind_drag_limit <= 0.0:
            msg = (
                f"Wind drag limit must be greater than 0.0. "
                f"Current value: {self.__wind_drag_limit}"
            )
            raise ValueError(msg)

        self.__bottom_friction_limit = model_configuration.get(
            "bottom_friction_limit", self.__bottom_friction_limit
        )
        if self.__bottom_friction_limit < 0.0:
            msg = (
                f"Bottom friction limit must be greater than or equal to 0.0. "
                f"Current value: {self.__bottom_friction_limit}"
            )
            raise ValueError(msg)

        self.__advection = model_configuration.get("advection", self.__advection)
        self.__use_self_attraction_and_loading = model_configuration.get(
            "self_attraction_and_loading", self.__use_self_attraction_and_loading
        )
        self.__use_direct_velmin_calculation = model_configuration.get(
            "use_direct_velmin", self.__use_direct_velmin_calculation
        )
        self.__use_hf_calculation = model_configuration.get(
            "use_hf_calculation", self.__use_hf_calculation
        )
        self.__station_partial_wet_fix_active = model_configuration.get(
            "station_partial_wet_fix_active", self.__station_partial_wet_fix_active
        )
        self.__station_partial_wet_fix_option = model_configuration.get(
            "station_partial_wet_fix_option", self.__station_partial_wet_fix_option
        )
        self.__implicit_gravity_wave = model_configuration.get(
            "implicit_gravity_wave", self.__implicit_gravity_wave
        )
        self.__slope_limiter_active = model_configuration.get(
            "slope_limiter_active", self.__slope_limiter_active
        )
        self.__slope_limiter_value = model_configuration.get(
            "slope_limiter_value", self.__slope_limiter_value
        )
        self.__wind_limiter_active = model_configuration.get(
            "wind_limiter_active", self.__wind_limiter_active
        )
        self.__coordinate_system = model_configuration.get(
            "coordinate_system", self.__coordinate_system
        )
        self.__use_vew1d_wet_perimeter = model_configuration.get(
            "use_vew1d_wet_perimeter", self.__use_vew1d_wet_perimeter
        )

        if "coordinate_rotation" in model_configuration:
            coors = model_configuration["coordinate_rotation"]
            self.__coordinate_rotation_x = coors[0]
            self.__coordinate_rotation_y = coors[1]

        self.__update_swan_model_parameters(model_configuration)
        self.__use_full_tip = model_configuration.get(
            "full_tide_potential", self.__use_full_tip
        )

    def __update_swan_model_parameters(self, model_configuration: dict) -> None:
        """
        Updates the SWAN model parameters with the values from the model configuration dictionary.

        Args:
            model_configuration: Dictionary containing the model configuration

        Returns:
            None
        """
        self.__swan_max_iterations = model_configuration.get(
            "swan_max_iterations", self.__swan_max_iterations
        )
        self.__swan_convergence_npts = model_configuration.get(
            "swan_convergence_npts", self.__swan_convergence_npts
        )
        self.__wave_coupling_interval = model_configuration.get(
            "wave_coupling_interval", self.__wave_coupling_interval
        )
        self.__swan_spectral_directions = model_configuration.get(
            "swan_spectral_directions", self.__swan_spectral_directions
        )
        if self.__swan_spectral_directions < 0:
            msg = (
                f"SWAN spectral directions must be greater than 0. "
                f"Current value: {self.__swan_spectral_directions}"
            )
            raise ValueError(msg)
        self.__swan_spectral_frequency_bins = model_configuration.get(
            "swan_spectral_frequency_bins", self.__swan_spectral_frequency_bins
        )
        if self.__swan_spectral_frequency_bins < 0:
            msg = (
                f"SWAN spectral frequency bin count be greater than 0. "
                f"Current value: {self.__swan_spectral_frequency_bins}"
            )
            raise ValueError(msg)
        self.__swan_spectral_frequency_minimum = model_configuration.get(
            "swan_spectral_frequency_minimum", self.__swan_spectral_frequency_minimum
        )
        if self.__swan_spectral_frequency_minimum < 0.0:
            msg = (
                f"SWAN minimum frequency must be greater than 0.0. "
                f"Current value: {self.__swan_spectral_frequency_minimum}"
            )
            raise ValueError(msg)
        self.__swan_spectral_frequency_maximum = model_configuration.get(
            "swan_spectral_frequency_maximum", self.__swan_spectral_frequency_maximum
        )
        if self.__swan_spectral_frequency_maximum < 0.0:
            msg = (
                f"SWAN maximum frequency must be greater than 0.0. "
                f"Current value: {self.__swan_spectral_frequency_maximum}"
            )
            raise ValueError(msg)
        if (
            self.__swan_spectral_frequency_maximum
            <= self.__swan_spectral_frequency_minimum
        ):
            msg = (
                f"SWAN maximum frequency must be greater than the minimum frequency. "
                f"Current values: {self.__swan_spectral_frequency_maximum}, {self.__swan_spectral_frequency_minimum}"
            )
            raise ValueError(msg)
        self.__swan_physics_version = model_configuration.get(
            "swan_physics_version", self.__swan_physics_version
        )
        self.__swan_physics_version = self.__swan_physics_version.lower()
        if (
            self.__swan_physics_version
            not in AdcircConfiguration.VALID_SWAN_PHYSICS_VERSIONS
        ):
            msg = (
                f"Invalid SWAN physics version: {self.__swan_physics_version}. "
                f"Valid options are: {AdcircConfiguration.VALID_SWAN_PHYSICS_VERSIONS}"
            )
            raise ValueError(msg)

    def set_traditional_preset(self) -> None:
        """
        Sets the model configuration to the traditional ADCIRC configuration.

        Returns:
            None

        """
        self.__solver = "implicit"
        self.__turbulence = "eddy_viscosity"
        self.__a00 = 0.35
        self.__b00 = 0.30
        self.__c00 = 0.35
        self.__wind_drag_formula = "default"
        self.__wind_drag_limit = 0.0025
        self.__bottom_friction_limit = 0.0010
        self.__tau0 = 0.005
        self.__eddy_viscosity_coefficient = 2.0
        self.__advection = False
        self.__implicit_gravity_wave = False

    def set_pringle_preset(self, time_step: float) -> None:
        """
        Sets the model configuration to the Pringle ADCIRC configuration.

        Args:
            time_step: The time step of the model.

        Returns:
            None

        """
        self.__solver = "implicit"
        self.__turbulence = "smagorinsky"
        self.__a00 = 0.50
        self.__b00 = 0.50
        self.__c00 = 0.0
        self.__wind_drag_formula = "default"
        self.__wind_drag_limit = 0.0025
        self.__bottom_friction_limit = 0.0010
        self.__tau0 = 8.0 / (5.0 * time_step)
        self.__smagorinsky_coefficient = 0.2
        self.__advection = True
        self.__implicit_gravity_wave = True

    def set_explicit_preset(self) -> None:
        """
        Sets the model configuration to the explicit ADCIRC configuration.

        Returns:
            None

        """
        self.__solver = "explicit"
        self.__turbulence = "smagorinsky"
        self.__a00 = 0.0
        self.__b00 = 1.0
        self.__c00 = 0.0
        self.__wind_drag_formula = "default"
        self.__wind_drag_limit = 0.0025
        self.__bottom_friction_limit = 0.0010
        self.__tau0 = 0.005
        self.__smagorinsky_coefficient = 0.2
        self.__advection = True
        self.__implicit_gravity_wave = False

    def set_jjw_preset(self) -> None:
        """
        Sets the model configuration to the JJW ADCIRC configuration.

        Returns:
            None

        """
        self.__solver = "implicit"
        self.__turbulence = "smagorinsky"
        self.__a00 = 0.8
        self.__b00 = 0.2
        self.__c00 = 0.0
        self.__wind_drag_formula = "default"
        self.__wind_drag_limit = 0.0025
        self.__bottom_friction_limit = 0.0010
        self.__tau0 = 0.05
        self.__smagorinsky_coefficient = 0.2
        self.__advection = True
        self.__implicit_gravity_wave = True
        self.__wind_limiter_active = True
        self.__slope_limiter_active = True
        self.__slope_limiter_value = 0.0004
        self.__use_direct_velmin_calculation = True

    def solver(self) -> str:
        """
        Returns the solver type.

        Returns:
            str: The solver type.

        """
        return self.__solver

    def turbulence_model(self) -> str:
        """
        Returns the turbulence model.

        Returns:
            str: The turbulence model.

        """
        return self.__turbulence

    def time_weighting_coefficients(self) -> tuple[float, float, float]:
        """
        Returns the time weighting coefficients.

        Returns:
            Tuple[float, float, float]: The time weighting coefficients.

        """
        return self.__a00, self.__b00, self.__c00

    def wind_drag_formula(self) -> str:
        """
        Returns the wind drag formula string

        Returns:
            str: The wind drag formula string.

        """
        return self.__wind_drag_formula

    def wind_drag_limit(self) -> float:
        """
        Returns the wind drag limit

        Returns:
            float: The wind drag limit.

        """
        return self.__wind_drag_limit

    def bottom_friction_limit(self) -> float:
        """
        Returns the bottom friction limit

        Returns:
            float: The bottom friction limit.

        """
        return self.__bottom_friction_limit

    def tau0(self) -> float:
        """
        Returns the tau0 value

        Returns:
            float: The tau0 value.

        """
        return self.__tau0

    def h0(self) -> float:
        """
        Returns the h0 value

        Returns:
            float: The h0 value.

        """
        return self.__h0

    def velmin(self) -> float:
        """
        Returns the velmin value

        Returns:
            float: The velmin value.

        """
        return self.__velmin

    def smagorinsky_coefficient(self) -> float:
        """
        Returns the Smagorinsky coefficient

        Returns:
            float: The Smagorinsky coefficient.

        """
        return self.__smagorinsky_coefficient

    def eddy_viscosity_coefficient(self) -> float:
        """
        Returns the eddy viscosity coefficient

        Returns:
            float: The eddy viscosity coefficient.

        """
        return self.__eddy_viscosity_coefficient

    def advection(self) -> bool:
        """
        Returns the advection flag

        Returns:
            bool: The advection flag.

        """
        return self.__advection

    def implicit_gravity_wave(self) -> bool:
        """
        Returns the implicit gravity wave flag

        Returns:
            bool: The implicit gravity wave flag.

        """
        return self.__implicit_gravity_wave

    def slope_limiter_active(self) -> bool:
        """
        Returns the slope limiter flag

        Returns:
            bool: The slope limiter flag.

        """
        return self.__slope_limiter_active

    def slope_limiter_value(self) -> float:
        """
        Returns the slope limiter value

        Returns:
            float: The slope limiter value.

        """
        return self.__slope_limiter_value

    def wind_limiter_active(self) -> bool:
        """
        Returns the wind limiter flag

        Returns:
            bool: The wind limiter flag.

        """
        return self.__wind_limiter_active

    def use_direct_velmin_calculation(self) -> bool:
        """
        Returns the use direct velmin calculation flag

        Returns:
            bool: The use direct velmin calculation flag.

        """
        return self.__use_direct_velmin_calculation

    def use_hf_calculation(self) -> bool:
        """
        Returns the use hf calculation flag

        Returns:
            bool: The use hf calculation flag.

        """
        return self.__use_hf_calculation

    def station_partial_wet_fix_active(self) -> bool:
        """
        Returns the station partial wet fix active flag

        Returns:
            bool: The station partial wet fix active flag.

        """
        return self.__station_partial_wet_fix_active

    def station_partial_wet_fix_option(self) -> int:
        """
        Returns the station partial wet fix option

        Returns:
            int: The station partial wet fix option.

        """
        return self.__station_partial_wet_fix_option

    def use_self_attraction_and_loading(self) -> bool:
        """
        Returns the use self attraction and loading flag

        Returns:
            bool: The use self attraction and loading flag.

        """
        return self.__use_self_attraction_and_loading

    def swan_max_iterations(self) -> int:
        """
        Returns the maximum number of iterations for SWAN

        Returns:
            int: The maximum number of iterations for SWAN.

        """
        return self.__swan_max_iterations

    def swan_convergence_npts(self) -> int:
        """
        Returns the percentage of points that must converge in SWAN

        Returns:
            int: The percentage of points that must converge in SWAN.

        """
        return self.__swan_convergence_npts

    def wave_coupling_interval(self) -> int:
        """
        Returns the wave coupling interval

        Returns:
            int: The wave coupling interval.

        """
        return self.__wave_coupling_interval

    def coordinate_system(self) -> int:
        """
        Returns the coordinate system

        Returns:
            int: The coordinate system.

        """
        return self.__coordinate_system

    def quadratic_friction_coefficient(self) -> float:
        """
        Returns the quadratic friction coefficient

        Returns:
            float: The quadratic friction coefficient.

        """
        return self.__quadratic_friction_coefficient

    def coordinate_rotation_x(self) -> float:
        """
        Returns the coordinate rotation x value

        Returns:
            float: The coordinate rotation x value.

        """
        return self.__coordinate_rotation_x

    def coordinate_rotation_y(self) -> float:
        """
        Returns the coordinate rotation y value

        Returns:
            float: The coordinate rotation y value.

        """
        return self.__coordinate_rotation_y

    def coordinate_rotation(self) -> Optional[tuple[float, float]]:
        """
        Returns the coordinate rotation values as a tuple

        Returns:
            Tuple[float, float]: The coordinate rotation values as a tuple.

        """
        if self.__coordinate_rotation_x and self.__coordinate_rotation_y:
            return self.__coordinate_rotation_x, self.__coordinate_rotation_y
        return None

    def hbreak(self) -> float:
        """
        Returns the hbreak value

        Returns:
            float: The hbreak value.

        """
        return self.__hbreak

    def ftheta(self) -> float:
        """
        Returns the ftheta value

        Returns:
            float: The ftheta value.

        """
        return self.__ftheta

    def fgamma(self) -> float:
        """
        Returns the fgamma value

        Returns:
            float: The fgamma value.

        """
        return self.__fgamma

    def swan_physics_version(self) -> str:
        """
        Returns the SWAN physics version

        Returns:
            str: The SWAN physics version.

        """
        return self.__swan_physics_version

    def swan_spectral_directions(self) -> int:
        """
        Returns the SWAN spectral directions

        Returns:
            int: The SWAN spectral directions.

        """
        return self.__swan_spectral_directions

    def swan_spectral_frequency_bins(self) -> int:
        """
        Returns the SWAN spectral frequencies

        Returns:
            int: The SWAN spectral frequencies.

        """
        return self.__swan_spectral_frequency_bins

    def swan_spectral_frequency_minimum(self) -> float:
        """
        Returns the SWAN minimum frequency

        Returns:
            float: The SWAN minimum frequency.

        """
        return self.__swan_spectral_frequency_minimum

    def swan_spectral_frequency_maximum(self) -> float:
        """
        Returns the SWAN maximum frequency

        Returns:
            float: The SWAN maximum frequency.

        """
        return self.__swan_spectral_frequency_maximum

    def set_output_option(self, output_type: str, value: bool) -> None:
        """
        Sets the output option for the ADCIRC model

        Args:
            output_type: The type of output to set
            value: The value to set the output option to

        Returns:
            None

        """
        if output_type in self.__adcirc_output_dict:
            self.__adcirc_output_dict[output_type] = value
        else:
            msg = f"Invalid output type: {output_type}"
            raise ValueError(msg)

    def output_option(self, output_type: str) -> bool:
        """
        Returns the value of the output option

        Args:
            output_type: The type of output to return

        Returns:
            bool: The value of the output option

        """
        if output_type in self.__adcirc_output_dict:
            return self.__adcirc_output_dict[output_type]
        msg = f"Invalid output type: {output_type}"
        raise ValueError(msg)

    def use_full_tide_potential(self) -> bool:
        """
        Returns the use full tide potential flag

        Returns:
            bool: The use full tide potential flag.

        """
        return self.__use_full_tip

    def use_vew1d_wet_perimeter(self) -> bool:
        """
        Returns the use vew1d wet perimeter flag

        Returns:
            bool: The use vew1d wet perimeter flag.

        """
        return self.__use_vew1d_wet_perimeter
