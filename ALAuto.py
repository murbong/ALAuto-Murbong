import argparse
import re
import sys
import time
import traceback
from datetime import datetime, timedelta

import keyboard

from modules.combat import CombatModule
from modules.commission import CommissionModule
from modules.enhancement import EnhancementModule
from modules.event import EventModule
from modules.headquarters import HeadquartersModule
from modules.mission import MissionModule
from modules.research import ResearchModule
from modules.retirement import RetirementModule
from util.adb import Adb
from util.config import Config
from util.logger import Logger
from util.stats import Stats
from util.updater import UpdateUtil
from util.utils import Utils

paused = False


def toggle_pause():
    global paused
    paused = not paused
    if paused:
        Logger.log_msg("Pausing script.")
    else:
        Logger.log_msg("Resuming script.")


class ALAuto(object):
    def __init__(self, config):
        """Initialize the automation workflow and enabled modules."""
        self.config = config
        self.oil_limit = 0
        self.stats = Stats(config)
        self.modules = {
            'updates': None,
            'combat': None,
            'commissions': None,
            'enhancement': None,
            'missions': None,
            'retirement': None,
            'headquarters': None,
            'research': None,
            'event': None
        }

        if self.config.updates['enabled']:
            self.modules['updates'] = UpdateUtil(self.config)
        if self.config.commissions['enabled']:
            self.modules['commissions'] = CommissionModule(self.config, self.stats)
        if self.config.enhancement['enabled']:
            self.modules['enhancement'] = EnhancementModule(self.config, self.stats)
        if self.config.missions['enabled']:
            self.modules['missions'] = MissionModule(self.config, self.stats)
        if self.config.retirement['enabled']:
            self.modules['retirement'] = RetirementModule(self.config, self.stats)
        if self.config.dorm['enabled'] or self.config.academy['enabled']:
            self.modules['headquarters'] = HeadquartersModule(self.config, self.stats)
        if self.config.combat['enabled']:
            self.modules['combat'] = CombatModule(
                self.config,
                self.stats,
                self.modules['retirement'],
                self.modules['enhancement']
            )
            self.oil_limit = self.config.combat['oil_limit']
        if self.config.research['enabled']:
            self.modules['research'] = ResearchModule(self.config, self.stats)
        if self.config.events['enabled']:
            self.modules['event'] = EventModule(self.config, self.stats)

        self.print_stats_check = True
        self.next_combat = datetime.now()

    def run_update_check(self):
        if self.modules['updates'] and self.modules['updates'].checkUpdate():
            Logger.log_warning("A new release is available, please check the github.")

    def should_sortie(self):
        """Check whether combat or event sortie should run now."""
        return (
            (self.modules['combat'] or self.modules['event'])
            and self.next_combat != 0
            and self.next_combat < datetime.now()
            and Utils.check_oil(self.oil_limit)
        )

    def run_sortie_cycle(self):
        self.run_event_cycle()
        self.run_combat_cycle()
        self.run_enhancement_cycle()
        self.run_retirement_cycle()

    def run_combat_cycle(self):
        if not self.modules['combat']:
            self.next_combat = 0
            return

        result = self.modules['combat'].combat_logic_wrapper()
        if result in (1, 2):
            Logger.log_msg("Completed combat cycle.")
            self.print_stats_check = True
        if result == 3:
            Logger.log_warning(
                "Ships morale is too low, entering standby mode for {} hour/s.".format(
                    self.config.combat['low_mood_sleep_time']
                )
            )
            self.next_combat = datetime.now() + timedelta(hours=self.config.combat['low_mood_sleep_time'])
            self.print_stats_check = False
        if result == 4:
            Logger.log_warning("Dock is full, need to retire/enhance.")
            Logger.log_error("Retirement and Enhancement aren't enabled or both failed to exectute their task, exiting.")
            sys.exit()
        if result == 5:
            Logger.log_warning("Failed to defeat enemy.")
            self.print_stats_check = False

    def run_commission_cycle(self):
        if self.modules['commissions']:
            self.modules['commissions'].commission_logic_wrapper()

    def run_enhancement_cycle(self):
        if self.modules['enhancement']:
            self.modules['enhancement'].enhancement_logic_wrapper()

    def run_mission_cycle(self):
        if self.modules['missions']:
            self.modules['missions'].mission_logic_wrapper()

    def run_retirement_cycle(self):
        if self.modules['retirement']:
            self.modules['retirement'].retirement_logic_wrapper()

    def run_hq_cycle(self):
        if self.modules['headquarters']:
            self.modules['headquarters'].hq_logic_wrapper()

    def run_research_cycle(self):
        if self.modules['research']:
            self.modules['research'].research_logic_wrapper()

    def run_event_cycle(self):
        if self.modules['event']:
            self.modules['event'].event_logic_wrapper()

    def print_cycle_stats(self):
        if self.print_stats_check:
            self.stats.print_stats(Utils.check_oil(self.oil_limit))
        self.print_stats_check = False


def build_arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c',
        '--config',
        metavar=('CONFIG_FILE'),
        help='Use the specified configuration file instead of the default config.ini'
    )
    parser.add_argument('-d', '--debug', help='Enables debugging logs.', action='store_true')
    parser.add_argument('-l', '--legacy', help='Enables sed usage.', action='store_true')
    return parser


def load_config(args):
    config = Config(args.config if args.config else 'config.ini')
    if args.debug:
        Logger.log_info("Enabled debugging.")
        Logger.enable_debugging(Logger)
    if args.legacy:
        Logger.log_info("Enabled sed usage.")
        Adb.enable_legacy(Adb)
    return config


def initialize_adb(config):
    Adb.service = config.network['service']
    Adb.tcp = ':' in Adb.service
    adb = Adb()

    if not adb.init():
        Logger.log_error('Unable to connect to the service.')
        sys.exit()

    Logger.log_msg('Successfully connected to the service with transport_id({}).'.format(Adb.transID))
    output = Adb.exec_out('wm size').decode('utf-8').strip()
    if not re.search('1920x1080|1080x1920', output):
        Logger.log_error("Resolution is not 1920x1080, please change it.")
        sys.exit()

    Utils.assets = config.assets['server']
    Utils.init_screencap_mode(config.screenshot['mode'])


def write_traceback():
    with open("traceback.log", "w") as handle:
        traceback.print_exc(None, handle, True)


def run_loop(script):
    keyboard.add_hotkey('ctrl+p', toggle_pause)

    while True:
        if paused:
            time.sleep(1)
            continue

        Utils.update_screen()

        if Utils.find_and_touch("menu/confirm"):
            Utils.script_sleep(1)
        if not Utils.find("menu/button_battle"):
            Utils.button_back()
            Utils.script_sleep(1)
            continue
        if Utils.find("commission/alert_completed"):
            script.run_commission_cycle()
            script.print_cycle_stats()
        if Utils.find("mission/alert_completed"):
            script.run_mission_cycle()
        if Utils.find("headquarters/hq_alert"):
            script.run_hq_cycle()
        if Utils.find("research/lab_alert"):
            script.run_research_cycle()
        if script.should_sortie():
            script.run_sortie_cycle()
            script.print_cycle_stats()
        else:
            Logger.log_msg("Nothing to do, will check again in a few minutes.")
            Utils.script_sleep(60)


def main():
    args = build_arg_parser().parse_args()
    config = load_config(args)
    script = ALAuto(config)
    script.run_update_check()
    initialize_adb(config)

    try:
        run_loop(script)
    except KeyboardInterrupt:
        Logger.log_msg("Received keyboard interrupt from user. Closing...")
        write_traceback()
        script.stats.print_stats(0)
        sys.exit(0)
    except SystemExit:
        pass
    except Exception:
        Logger.log_error("An error occurred. For more info check the traceback.log file.")
        write_traceback()
        sys.exit(1)


if __name__ == '__main__':
    main()
