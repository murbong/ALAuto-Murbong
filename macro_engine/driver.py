from util.logger import Logger

try:
    from util.utils import Utils
except ImportError:
    Utils = None


class DriverError(Exception):
    """Raised when a runtime driver cannot be created or used."""


class MacroDriver(object):
    """Abstract automation driver used by the macro runtime."""

    def update_screen(self):
        raise NotImplementedError()

    def wait_update_screen(self, seconds=None):
        raise NotImplementedError()

    def capture_frame(self):
        raise NotImplementedError()

    def find_image(self, image, similarity, color=False, interrupt_if_not_found=False, use_mask=False):
        raise NotImplementedError()

    def tap_image(self, image, similarity, color=False, use_mask=False):
        raise NotImplementedError()

    def tap_region(self, region):
        raise NotImplementedError()

    def back(self):
        raise NotImplementedError()

    def swipe(self, x1, y1, x2, y2, ms):
        raise NotImplementedError()

    def get_region_color_average(self, region):
        raise NotImplementedError()

    def check_oil(self, limit=0):
        return 0

    def supports_live_preview(self):
        return False


class AdbMacroDriver(MacroDriver):
    """Driver implementation backed by the legacy Utils/ADB stack."""

    def __init__(self, config):
        if Utils is None:
            raise DriverError("Runtime dependencies are unavailable. Install requirements before running macros.")
        self.config = config

    def update_screen(self):
        Utils.update_screen()

    def wait_update_screen(self, seconds=None):
        Utils.wait_update_screen(seconds)

    def capture_frame(self):
        if getattr(Utils, 'color_screen', None) is None:
            return None
        return Utils.color_screen.copy()

    def find_image(self, image, similarity, color=False, interrupt_if_not_found=False, use_mask=False):
        return Utils.find(image, similarity, color, interrupt_if_not_found)

    def tap_image(self, image, similarity, color=False, use_mask=False):
        return Utils.find_and_touch(image, similarity, color)

    def tap_region(self, region):
        Utils.touch_randomly(region)

    def back(self):
        Utils.button_back()

    def swipe(self, x1, y1, x2, y2, ms):
        Utils.swipe(x1, y1, x2, y2, ms)

    def get_region_color_average(self, region):
        return Utils.get_region_color_average(region)

    def check_oil(self, limit=0):
        return Utils.check_oil(limit)

    def supports_live_preview(self):
        return True


class UnsupportedMacroDriver(MacroDriver):
    """Placeholder for future non-ADB runtimes."""

    def __init__(self, driver_type):
        self.driver_type = driver_type

    def _raise(self):
        raise DriverError("Driver type '{}' is not implemented yet.".format(self.driver_type))

    def update_screen(self):
        self._raise()

    def wait_update_screen(self, seconds=None):
        self._raise()

    def capture_frame(self):
        self._raise()

    def find_image(self, image, similarity, color=False, interrupt_if_not_found=False, use_mask=False):
        self._raise()

    def tap_image(self, image, similarity, color=False, use_mask=False):
        self._raise()

    def tap_region(self, region):
        self._raise()

    def back(self):
        self._raise()

    def swipe(self, x1, y1, x2, y2, ms):
        self._raise()

    def get_region_color_average(self, region):
        self._raise()


def create_macro_driver(config):
    driver_type = 'adb'
    driver_spec = getattr(config, 'driver', None)
    if isinstance(driver_spec, dict) and driver_spec.get('type'):
        driver_type = str(driver_spec.get('type')).strip().lower()
    Logger.log_debug("Creating macro driver '{}'".format(driver_type))
    if driver_type == 'adb':
        return AdbMacroDriver(config)
    return UnsupportedMacroDriver(driver_type)
