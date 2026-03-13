import json
import os
import re
import traceback

from macro_engine.driver import create_macro_driver
from util.adb import Adb
from util.config import Config
from util.logger import Logger
from util.utils import Utils


def _apply_cli_runtime_flags(args):
    if args.debug:
        Logger.log_info('Enabled debugging.')
        Logger.enable_debugging(Logger)
    if args.legacy:
        Logger.log_info('Enabled sed usage.')
        Adb.enable_legacy(Adb)


def load_config(args):
    config = Config(args.config if args.config else 'config.json')
    _apply_cli_runtime_flags(args)
    return config


def load_macro_file(path):
    with open(path, 'r', encoding='utf-8-sig') as handle:
        return json.load(handle)


def load_runtime_config(args, macro_path=None):
    if macro_path and os.path.exists(macro_path):
        macro = load_macro_file(macro_path)
        runtime = macro.get('runtime')
        if isinstance(runtime, dict):
            config = Config.from_dict(runtime, source=macro_path + ':runtime')
            _apply_cli_runtime_flags(args)
            return config
    return load_config(args)


def initialize_adb(config):
    driver_type = str(getattr(config, 'driver', {}).get('type', 'adb')).strip().lower()
    if driver_type != 'adb':
        return

    Adb.service = config.network['service']
    Adb.tcp = ':' in Adb.service
    adb = Adb()
    if not adb.init():
        Logger.log_error('Unable to connect to the service.')
        raise SystemExit(1)

    Logger.log_msg('Successfully connected to the service with transport_id({}).'.format(Adb.transID))
    output = Adb.exec_out('wm size').decode('utf-8').strip()
    if not re.search('1920x1080|1080x1920', output):
        Logger.log_error('Resolution is not 1920x1080, please change it.')
        raise SystemExit(1)

    Utils.assets = config.assets['server']
    Utils.init_screencap_mode(config.screenshot['mode'])


def create_runtime_driver(config):
    initialize_adb(config)
    return create_macro_driver(config)


def write_traceback():
    with open('traceback.log', 'w', encoding='utf-8') as handle:
        traceback.print_exc(None, handle, True)
