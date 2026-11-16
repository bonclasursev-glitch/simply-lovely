import numpy as np
import fastf1


class PhysicalFormulas:
    def __init__(self, config):
        self.config = config
        self.gravity = config['PHYSICAL_VARIABLES']['G']
        self.air_density = config['PHYSICAL_VARIABLES']['rho']
        self.car_mass = config['VEHICLE_PARAMETERS']['car_mass']
        self.fuel_mass = config['VEHICLE_PARAMETERS']['fuel_mass']
        self.lift_coef = config['VEHICLE_PARAMETERS']['ClA']
        self.drag_coef = config['VEHICLE_PARAMETERS']['CdA']
        self.engine_power = config['VEHICLE_PARAMETERS']['power']
        self.mu_ref = config['VEHICLE_PARAMETERS']['mu_ref']
        self.load_sens = config['VEHICLE_PARAMETERS']['load_sensitivity']
        self.fz_ref = config['VEHICLE_PARAMETERS']['Fz_ref']
        self.brake_force_max = config['VEHICLE_PARAMETERS']['brake_force_max']

    # TODO: add drs eauivalent to all formulas if required
    def drag_formula(self, v):
        return 0.5 * self.air_density * self.drag_coef * v * v

    def downforce_formula(self, v):
        return 0.5 * self.air_density * self.lift_coef * v * v

    def overall_vehicle_mass(self):
        return self.car_mass + self.fuel_mass

    def normal_load(self, v):
        return self.car_mass * self.gravity + self.downforce_formula(self, v)

    def friction_coefficient(self, fz):
        return self.mu_ref * (fz/ self.fz_ref) ** (-self.load_sens)

    def grip_force(self, v):
        fz = self.normal_load(v)
        return self.friction_coefficient(fz) * fz

    def straight_top_speed(self):
        if self.drag_coef <=1e-6:
            return 500
        return (2.0 * self.engine_power / (self.air_density * self.drag_coef)) ** (1/3)
    
    def arc_length(self, corner_radius, corner_angle):
        return corner_radius * abs(np.deg2rad(corner_angle))


class Track:
    def __init__():
        pass

    @property
    def ds(self):
        return float(self.s[1] - self.s[0])

    @property
    def length(self):
        return float(self.s[-1] + self.ds)

# TODO: add drs equivalent
    
    def create_mock_track(sections, ds=5, name="mock"):
        # This is a very simple track, only used for sanity check and to test the model
        kappa_segments = []
        for section in sections:
            if section[0] == "corner":
                _, corner_radius, corner_angle = section
                arc_length = self.arc_length(corner_radius, corner_angle)
                n = max(1, int(round(arc_length/ds)))
                kappa_segments.append(np.full(n, np.sign(corner_angle)/corner_radius))
            elif section[0] == "straight":
                n = max(1, int(round(section[1]/ds)))
                kappa_segments.append(np.zeros(n))
            else:
                raise ValueError(f"Please check this section type as it is not recognised: {section[0]}")

        kappa = np.concatenate(kappa_segments)
        s = np.arange(len(kappa)) * ds

        heading = np.cumsum(kappa) * ds
        x = np.cumsum(np.cos(heading)) * ds
        y = np.cumsum(np.sin(heading)) * ds

        return Track(name, s, kappa, x, y)

def calculate_corner_speed(kappa, car, v_cap):
    def _residual_grip(self, v):
        return grip_force(v, car) - self.car_mass * v * v * kappa_magnitude
    
    kappa_magnitude = abs(kappa)        
    
    if v_cap is None:
        v_cap = straight_top_speed(car)

    # Not solving for straights
    if kappa_magnitude < 1e-10:
        return v_cap
    # max allowed speed if the car can take it
    elif residual_risk(v_cap) >= 0:
        return v_cap
    # speed for which residual_grip = 0 --> max cornering speed
    else return brentq(residual_grip, 0.1, v_cap, xtol = 1e-4)

def cornering_ceiling(track=Track, car):
    v_cap = straight_top_speed(car)
    out = np.empty_like(track.s)
    for i, k in enumerate(zip(Track.kappa)):
        out[i] = calculate_corner_speed(kappa, car, v_cap)
    
    return out

def longitudinal_grip(self, v, kappa, car):
    F_total = grip_force(v, car)
    F_lat = self.car_mass * v * v * abs(kappa)

    if F_lat >= F_total:
        grip_lon = 0
    else grip_lon = np.sqrt(F_total - F_lat * F_lat)

    return float(grip_lon)

def maximum_acceleration(self, v, kappa, car):
    v = max(1, v)
    F_traction = longitudinal_grip(v, kappa, car)
    F_power = self.engine_power / v
    F_net = min(F_traction F_power) - drag_formula(v, car)
    max_acceleration = F_net/ self.car_mass

    return max_acceleration

def maximum_deceleration(self, v, kappa, car):
    v = max(1, v)
    F_brake = min(longitudinal_grip(v, kappa, car), self.brake_force_max)
    max_deceleration = (F_brake + drag_formula(v, car))/ self.car_mass

@dataclass
class SimulationResult:
    track:Track
    car:Car
    v: np.ndarray
    v_limit: np.ndarray
    lap_time: float
    a_long: np.ndarray
    a_lat: np.nd_array
    apex_index: np.ndarray

    @property
    def v_kph(self):
        return self.v *3.6
