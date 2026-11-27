#!/usr/bin/env python3
"""Crabby installer (Windows).

    python install.py                 install (or update) and turn on "start with Claude"
    python install.py --no-autostart  install, but only start the pet with /pet
    python install.py --uninstall     remove everything this script added

It copies the pet and the Claude mod into your Claude config folder (normally
C:\\Users\\<you>\\.claude) and adds one line to that folder's settings.json.
The settings file is backed up first. Nothing is downloaded and nothing leaves your PC.
"""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = 'crabby'


def claude_dir(arg):
    if arg:
        return os.path.abspath(arg)
    env = os.environ.get('CLAUDE_CONFIG_DIR')
    if env:
        return os.path.abspath(env)
    return os.path.join(os.path.expanduser('~'), '.claude')


def fwd(p):
    return p.replace('\\', '/')


def load_settings(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8-sig') as fh:
        text = fh.read().strip()
    return json.loads(text) if text else {}


def save_settings(path, data):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write('\n')


def backup(path):
    if os.path.exists(path):
        dst = '%s.bak-%s-%s' % (path, NAME, time.strftime('%Y%m%d%H%M%S'))
        shutil.copy2(path, dst)
        return dst
    return None


MAC = sys.platform == 'darwin'
SEP = ':' if MAC else ';'   # CLAUDE_CODE_PLUGIN_DIRS is a PATH-style list


def dirs_of(env):
    return [d for d in (env.get('CLAUDE_CODE_PLUGIN_DIRS') or '').split(SEP) if d.strip()]


def same(a, b):
    a, b = os.path.expanduser(a), os.path.expanduser(b)
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def install(args):
    if sys.platform != 'win32' and not MAC:
        sys.exit('Crabby only runs on Windows and macOS for now.')
    try:
        import tkinter
    except Exception:
        sys.exit('This Python has no tkinter. Install Python from python.org (the normal installer includes tkinter) and run this again.')
    if MAC and tkinter.TkVersion >= 9:
        sys.exit('This Python carries Tk %s, which draws see-through windows black on macOS. Run the installer with a Python '
                 'that carries Tk 8.6, for example:  uv python install 3.11.9  then  "$(uv python find 3.11.9)" install.py' % tkinter.TkVersion)

    base = claude_dir(args.claude_dir)
    pet_dir = os.path.join(base, NAME)
    mod_dir = os.path.join(base, 'mods', NAME)
    os.makedirs(pet_dir, exist_ok=True)

    for f in ('crab_pet.py', 'sprites.json', 'start.sh' if MAC else 'start.vbs'):
        shutil.copy2(os.path.join(HERE, 'pet', f), os.path.join(pet_dir, f))

    if MAC:
        with open(os.path.join(pet_dir, 'python.txt'), 'w', encoding='utf-8') as fh:
            fh.write(sys.executable + '\n')
    else:
        pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        with open(os.path.join(pet_dir, 'pythonw.txt'), 'w', encoding='utf-8') as fh:
            fh.write((pyw if os.path.exists(pyw) else '') + '\n')

    if os.path.isdir(mod_dir):
        shutil.rmtree(mod_dir)
    shutil.copytree(os.path.join(HERE, 'mod'), mod_dir)

    settings_path = os.path.join(base, 'settings.json')
    bak = backup(settings_path)
    data = load_settings(settings_path)
    env = data.setdefault('env', {})
    dirs = dirs_of(env)
    if not any(same(d, mod_dir) for d in dirs):
        dirs.append(fwd(mod_dir))
    env['CLAUDE_CODE_PLUGIN_DIRS'] = SEP.join(dirs)
    opts = data.setdefault('pluginConfigs', {}).setdefault(NAME, {}).setdefault('options', {})
    opts['autoStart'] = not args.no_autostart
    save_settings(settings_path, data)

    print('Crabby installed.')
    print('  pet:  ' + pet_dir)
    print('  mod:  ' + mod_dir)
    print('  settings updated: ' + settings_path + (' (backup: %s)' % os.path.basename(bak) if bak else ''))
    print('Now start a NEW Claude chat. The crab appears by itself' + ('' if not args.no_autostart else ' after you type /pet') + '.')
    print('Stop it any time with /pet.')


def uninstall(args):
    base = claude_dir(args.claude_dir)
    pet_dir = os.path.join(base, NAME)
    mod_dir = os.path.join(base, 'mods', NAME)
    if os.path.isdir(pet_dir):
        try:
            with open(os.path.join(pet_dir, 'quit'), 'w') as fh:
                fh.write('1')
            time.sleep(4)
        except OSError:
            pass
    settings_path = os.path.join(base, 'settings.json')
    if os.path.exists(settings_path):
        backup(settings_path)
        data = load_settings(settings_path)
        env = data.get('env', {})
        if isinstance(env, dict) and 'CLAUDE_CODE_PLUGIN_DIRS' in env:
            keep = [d for d in dirs_of(env) if not same(d, mod_dir)]
            if keep:
                env['CLAUDE_CODE_PLUGIN_DIRS'] = SEP.join(keep)
            else:
                del env['CLAUDE_CODE_PLUGIN_DIRS']
            if not env:
                data.pop('env', None)
        cfg = data.get('pluginConfigs', {})
        if isinstance(cfg, dict):
            cfg.pop(NAME, None)
            if not cfg:
                data.pop('pluginConfigs', None)
        save_settings(settings_path, data)
    for d in (mod_dir, pet_dir):
        shutil.rmtree(d, ignore_errors=True)
    print('Crabby removed. Your settings backup is next to settings.json.')


def main():
    ap = argparse.ArgumentParser(description='Install or remove Crabby.')
    ap.add_argument('--uninstall', action='store_true')
    ap.add_argument('--no-autostart', action='store_true', help='do not start the pet with Claude; use /pet instead')
    ap.add_argument('--claude-dir', help='Claude config folder (default: CLAUDE_CONFIG_DIR or ~/.claude)')
    args = ap.parse_args()
    (uninstall if args.uninstall else install)(args)


if __name__ == '__main__':
    main()
