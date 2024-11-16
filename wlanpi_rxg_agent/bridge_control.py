import logging

import dbus


class BridgeControl:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing BridgeControl")

        system_bus = dbus.SystemBus()
        systemd1 = system_bus.get_object(
            "org.freedesktop.systemd1", "/org/freedesktop/systemd1"
        )
        self.manager = dbus.Interface(systemd1, "org.freedesktop.systemd1.Manager")

    def enable(self) -> bool:
        try:
            self.manager.EnableUnitFiles(["wlanpi-mqtt-bridge.service"], False, True)
            self.manager.Reload()
            return True
        except Exception as e:
            self.logger.error(f"Failed to enable and reload: {e}")
            return False

    def disable(self) -> bool:
        try:
            self.manager.DisableUnitFiles(["wlanpi-mqtt-bridge.service"], False)
            self.manager.Reload()
            return True
        except Exception as e:
            self.logger.error(f"Failed to disable and reload: {e}")
            return False

    def restart(self):
        self.enable()
        try:
            self.manager.RestartUnit("wlanpi-mqtt-bridge.service", "fail")

        except Exception as e:
            self.logger.error(f"Failed to restart unit: {e}")
        else:
            self.logger.info("Restarted bridge service")
            return True
        return False

    def start(self) -> bool:
        self.enable()
        try:
            self.manager.StartUnit("wlanpi-mqtt-bridge.service", "fail")

        except Exception as e:
            self.logger.error(f"Failed to start unit: {e}")
        else:
            self.logger.info("Started bridge service")
            return True
        return False

    def stop(self):
        try:
            self.manager.StopUnit("wlanpi-mqtt-bridge.service", "fail")
        except Exception as e:
            self.logger.error(f"Failed to stop unit: {e}")
        else:
            self.logger.info("Stopped bridge service")
            return True
        return False
