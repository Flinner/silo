"""Shared configuration, CLI and terminal-menu regression tests.

Run from the checkout: bw python3 -m unittest discover -s tests -v
"""
import copy
import curses
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from click.testing import CliRunner

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'silo'))
# runpy's returned dict is a copy; functions share their original globals.
S = MODULE['read_cfg'].__globals__


class Screen:
    def __init__(self, keys=(), size=(24, 80)):
        self.keys = iter(keys)
        self.size = size
        self.frames = []
        self.frame = []

    def erase(self):
        self.frame = []

    def getmaxyx(self):
        return self.size

    def addnstr(self, y, x, text, width, attr=0):
        self.frame.append(text[:width])

    def refresh(self):
        self.frames.append(self.frame[:])

    def get_wch(self):
        return next(self.keys)

    def keypad(self, enabled):
        pass

    def timeout(self, milliseconds):
        pass

    def move(self, y, x):
        pass

    def clear(self):
        self.erase()


class SiloTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        tools = {name: S['Tool'](name, tool.env, root / ('host-' + name), cred=tool.cred,
                                login_cmd=tool.login_cmd) for name, tool in S['TOOLS'].items()}
        self.patch = patch.dict(S, ROOT=root / 'config', LOGINS=root / 'config/logins',
                                CONFIG=root / 'config/config.json', STATE=root / 'state',
                                RUNTIME=root / 'runtime', HOME=root / 'home', TOOLS=tools,
                                auto_check=lambda: None)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tool = tools['claude']
        self.runner = CliRunner()

    def invoke(self, args, **kwargs):
        result = self.runner.invoke(S['cli'], args, **kwargs)
        self.assertEqual(result.exit_code, 0, (result.output, result.exception))
        return result

    def seed(self):
        S['add_login'](self.tool, 'work')
        S['create'](self.tool, 'research', False, 'work')
        S['Configuration'].set_defaults(self.tool, 'research', 'work')

    def ui(self, keys=(), size=(24, 80)):
        return S['TerminalUI'](Screen(keys, size), 'claude')

    def test_schema_is_shared_and_defaults_are_independent(self):
        self.assertEqual(set(S['SETTINGS']), set(S['DEFAULTS']))
        first = S['Configuration'].effective({})
        first['writable'].append('/example')
        self.assertEqual(S['Configuration'].effective({})['writable'], [])
        for key, setting in S['SETTINGS'].items():
            self.assertEqual(setting.validate(key, setting.default), S['DEFAULTS'][key])

    def test_cli_and_tui_share_validation(self):
        result = self.runner.invoke(S['cli'], ['config', 'nice', '20'])
        self.assertNotEqual(result.exit_code, 0)
        with self.assertRaisesRegex(ValueError, 'between 0 and 19'):
            S['Configuration'].parse('nice', ['20'])
        self.invoke(['config', 'nice', '15'])
        self.assertEqual(S['read_cfg']()['nice'], 15)
        ui = self.ui()
        with patch.object(ui, 'prompt', return_value='7'):
            self.assertEqual(ui.edit_setting('nice', 15), 7)
        with patch.object(ui, 'prompt', return_value='20'):
            with self.assertRaises(ValueError):
                ui.edit_setting('nice', 15)

    def test_all_setting_types_validate(self):
        parse = S['Configuration'].parse
        self.assertTrue(parse('git_config', ['yes']))
        self.assertFalse(parse('git_config', ['false']))
        self.assertEqual(parse('writable', ['/path with spaces']), ['/path with spaces'])
        self.assertEqual(parse('brokered', ['{"gh": ["pr view"]}']), {'gh': ['pr view']})
        self.assertEqual(parse('logins', ['{"claude/research": "work"}']), {'claude/research': 'work'})
        self.assertEqual(parse('memory_max', ['4G']), '4G')
        for key, values in [('nice', ['bad']), ('git_config', ['maybe']), ('ionice', ['fast']),
                            ('writable', []), ('brokered', ['{"gh": "anything"}']),
                            ('logins', ['{"claude/../bad": "work"}']), ('memory_max', ['bad'])]:
            if key == 'writable':
                self.assertEqual(parse(key, values), [])
            else:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    parse(key, values)
        with self.assertRaises(ValueError):
            S['Configuration'].validate({'nice': True})
        with self.assertRaises(ValueError):
            S['Configuration'].validate({'writable': [3]})

    def test_atomic_save_preserves_unknown_fields_and_no_env(self):
        raw = {'nice': 4, 'future_setting': {'example': True}, 'ssh_keys': ['named-by-user']}
        S['Configuration'].save(raw)
        with patch.dict(os.environ, SILO_SSH_KEYS='environment-key'):
            self.assertEqual(S['load_cfg']()['ssh_keys'], ['environment-key'])
            self.invoke(['config', 'nice', '5'])
        saved = S['read_cfg']()
        self.assertEqual(saved['future_setting'], {'example': True})
        self.assertEqual(saved['ssh_keys'], ['named-by-user'])
        self.assertEqual(S['CONFIG'].stat().st_mode & 0o777, 0o600)
        previous = S['CONFIG'].read_text()
        with patch.object(Path, 'replace', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                S['Configuration'].save({'nice': 3})
        self.assertEqual(S['CONFIG'].read_text(), previous)
        self.assertFalse(list(S['ROOT'].glob('.config-*')))

    def test_edit_validates_before_changing_disk(self):
        S['Configuration'].save({'nice': 10})
        previous = S['CONFIG'].read_text()
        with patch.object(S['click'], 'edit', return_value='{"nice": 100}'):
            result = self.runner.invoke(S['cli'], ['config', '--edit'])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(S['CONFIG'].read_text(), previous)
        with patch.object(S['click'], 'edit', return_value='{"nice": 4}'):
            self.invoke(['config', '--edit'])
        self.assertEqual(S['read_cfg']()['nice'], 4)

    def test_settings_conflict_and_merge(self):
        S['Configuration'].save({'nice': 10})
        base = S['read_cfg']()
        draft = {**base, 'nice': 5}
        S['Configuration'].save({**base, 'ionice': 'normal'})
        S['Configuration'].commit(base, draft)
        self.assertEqual(S['read_cfg']()['ionice'], 'normal')
        base = S['read_cfg']()
        S['Configuration'].save({**base, 'nice': 12})
        with self.assertRaisesRegex(ValueError, 'changed elsewhere'):
            S['Configuration'].commit(base, {**base, 'nice': 3})
        self.assertEqual(S['read_cfg']()['nice'], 12)

    def test_load_rejects_invalid_file_types(self):
        S['ROOT'].mkdir()
        for raw in [{'nice': 'ten'}, []]:
            S['CONFIG'].write_text(json.dumps(raw))
            result = self.runner.invoke(S['cli'], ['config'])
            self.assertNotEqual(result.exit_code, 0)

    def test_names_cannot_escape_store(self):
        for name in ['', '../outside', '.', '..', 'bad/name', 'bad\nname']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                S['add_login'](self.tool, name)
        with self.assertRaises(ValueError):
            S['create'](self.tool, '../outside', False)

    def test_profile_login_operations_shared_with_cli(self):
        self.invoke(['claude', 'login', 'add', 'work'])
        self.invoke(['claude', 'new', 'research', '--login', 'work'])
        self.assertEqual(S['login_of'](self.tool, 'research'), 'work')
        with self.assertRaisesRegex(ValueError, 'profiles default'):
            S['delete_login'](self.tool, 'work')
        # Deletion does not read credentials, and retains the login store.
        S['delete_profile'](self.tool, 'research')
        self.assertTrue((S['LOGINS'] / 'claude/work').is_dir())
        self.assertNotIn('claude/research', S['read_cfg']()['logins'])
        self.invoke(['claude', 'login', 'rm', 'work', '-y'])
        self.assertFalse((S['LOGINS'] / 'claude/work').exists())

    def test_rename_preserves_history_and_account(self):
        self.seed()
        history = S['ROOT'] / 'claude/research/history.txt'
        history.write_text('conversation')
        self.invoke(['claude', 'rename', 'research', 'renamed'])
        self.assertEqual((S['ROOT'] / 'claude/renamed/history.txt').read_text(), 'conversation')
        self.assertEqual(S['login_of'](self.tool, 'renamed'), 'work')
        self.assertNotIn('claude/research', S['read_cfg']()['logins'])

    def test_rename_rolls_back_when_save_fails(self):
        self.seed()
        with patch.object(S['Configuration'], 'save', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                S['rename_profile'](self.tool, 'research', 'renamed')
        self.assertTrue((S['ROOT'] / 'claude/research').is_dir())
        self.assertFalse((S['ROOT'] / 'claude/renamed').exists())
        self.assertEqual(S['login_of'](self.tool, 'research'), 'work')

    def test_new_profile_does_not_create_a_login(self):
        self.invoke(['claude', 'new', 'work'])
        self.assertTrue((S['ROOT'] / 'claude/work').is_dir())
        self.assertFalse((S['LOGINS'] / 'claude/work').exists())
        self.assertEqual(S['Configuration'].launch(self.tool, 'work'), ('work', 'main'))

    def test_saved_login_defaults_apply_to_cli_and_tui(self):
        self.seed()
        with patch.dict(S, sandbox=lambda tool, name, login: ['bwrap', name, login], limits=lambda cfg: []), \
             patch.object(S['os'], 'execvp') as execute:
            self.invoke(['claude', '--profile=research'])
        execute.assert_called_once_with('bwrap', ['bwrap', 'research', 'work', 'claude'])
        self.assertEqual(S['Configuration'].launch(self.tool, 'research'), ('research', 'work'))

    def test_launch_uses_shared_sandbox_builder(self):
        self.seed()
        with patch.dict(S, sandbox=lambda tool, name, login: ['bwrap', name, login], limits=lambda cfg: ['nice']):
            self.assertEqual(S['launch_argv'](self.tool, 'research', args=['-c']),
                             ['nice', 'bwrap', 'research', 'work', 'claude', '-c'])
            with patch.object(S['subprocess'], 'run') as run:
                run.return_value.returncode = 0
                self.ui().run_agent(self.tool, 'research', 'work')
                run.assert_called_once_with(['nice', 'bwrap', 'research', 'work', 'claude'], close_fds=False)
            with patch.object(S['os'], 'execvp') as execute:
                self.invoke(['claude', '--profile=research', '--login=work', '-c'])
                execute.assert_called_once_with('nice', ['nice', 'bwrap', 'research', 'work', 'claude', '-c'])

    def test_named_flags_and_passthrough(self):
        with patch.dict(S, launch_argv=lambda tool, name, login, args: ['fake', tool.bin, *S['Configuration'].launch(tool, name, login), *args]):
            for argv, expected in [(['codex'], ['fake', 'codex', 'main', 'main']),
                                   (['claude', '--login=work'], ['fake', 'claude', 'main', 'work']),
                                   (['--profile=research', '--login=work', '-c'], ['fake', 'claude', 'research', 'work', '-c']),
                                   (['codex', '--profile', 'research', '--login', 'work', 'exec', 'hello'], ['fake', 'codex', 'research', 'work', 'exec', 'hello']),
                                   (['claude', '--profile=research', '--', '--login=agent'], ['fake', 'claude', 'research', 'main', '--login=agent']),
                                   (['research', '--login', 'work', '-c'], ['fake', 'claude', 'research', 'work', '-c'])]:
                with self.subTest(argv=argv), patch.object(S['os'], 'execvp') as execute:
                    self.invoke(argv)
                    execute.assert_called_once_with('fake', expected)
        for argv in [['claude', '--profile='], ['claude', '--login']]:
            self.assertEqual(self.runner.invoke(S['cli'], argv).exit_code, 2)

    def test_menu_startup_and_noninteractive_error(self):
        with patch.dict(S, open_tui=lambda tool: None) as patched:
            self.invoke([])
            self.invoke(['tui'])
            self.invoke(['codex', 'tui'])
        result = self.runner.invoke(S['cli'], [])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('interactive terminal', result.output)
        help = self.invoke(['--help']).output
        self.assertIn('[claude|codex]', help)
        self.assertIn('terminal menu', help)

    def test_menu_navigation_resize_and_quit(self):
        ui = self.ui([curses.KEY_DOWN, curses.KEY_RESIZE, '\n'])
        self.assertEqual(ui.menu('Example', ['one', 'two']), 1)
        with patch.object(S['curses'], 'curs_set'):
            self.ui(['q']).run()
            self.ui(['q'], size=(8, 30)).run()

    def test_dashboard_changes_selections_independently_and_launches(self):
        S['create'](self.tool, 'main', False)
        S['create'](self.tool, 'research', False)
        S['add_login'](self.tool, 'main')
        S['add_login'](self.tool, 'work')
        ui = self.ui(['l', 'j', 'p', 'j', '\n', 'q'])
        with patch.object(S['curses'], 'curs_set'), patch.object(ui, 'terminal') as terminal:
            ui.run()
        terminal.assert_called_once_with(ui.run_agent, self.tool, 'research', 'work')
        self.assertEqual(S['Configuration'].selections(self.tool), ('main', 'main'))

    def test_new_profile_flow_leaves_accounts_unchanged(self):
        S['add_login'](self.tool, 'work')
        ui = self.ui()
        with patch.object(ui, 'prompt', return_value='research'):
            self.assertEqual(ui.new_profile(), 'research')
        self.assertTrue((S['ROOT'] / 'claude/research').is_dir())
        self.assertFalse((S['LOGINS'] / 'claude/research').exists())
        self.assertEqual(S['Configuration'].selections(self.tool), ('main', 'main'))

    def test_account_authentication_does_not_use_persistent_profile(self):
        S['add_login'](self.tool, 'work')
        ui = self.ui()
        with patch.object(ui, 'terminal') as terminal:
            ui.authenticate(self.tool, 'work')
        terminal.assert_called_once_with(S['run_authentication'], self.tool, 'work')
        self.assertEqual(S['profile_names'](self.tool), [])

    def test_login_import_checks_account_before_creating_directory(self):
        with self.assertRaisesRegex(ValueError, 'not logged in'):
            S['add_login'](self.tool, 'work', True)
        self.assertFalse((S['LOGINS'] / 'claude/work').exists())
        self.tool.home.mkdir()
        # This is a test marker, never a real credential or authentication token.
        (self.tool.home / self.tool.cred).touch()
        with patch.dict(S, import_login=lambda tool, name: (S['LOGINS'] / tool.bin / name).mkdir(parents=True, exist_ok=True)):
            S['add_login'](self.tool, 'work', True)
        self.assertTrue((S['LOGINS'] / 'claude/work').is_dir())

    def test_settings_cancel_save_reset(self):
        S['Configuration'].save({'nice': 10})
        ui = self.ui()
        index = list(S['SETTINGS']).index('nice')
        with patch.object(ui, 'menu', side_effect=[index, None, 1]), \
             patch.object(ui, 'edit_setting', return_value=7):
            ui.settings()
        self.assertEqual(S['read_cfg']()['nice'], 10)
        with patch.object(ui, 'menu', side_effect=[index, 's']), \
             patch.object(ui, 'edit_setting', return_value=7):
            ui.settings()
        self.assertEqual(S['read_cfg']()['nice'], 7)
        with patch.object(ui, 'menu', side_effect=['r', index, 's']):
            ui.settings()
        self.assertNotIn('nice', S['read_cfg']())
        self.assertEqual(S['load_cfg']()['nice'], 10)

    def test_list_and_table_editors(self):
        ui = self.ui()
        with patch.object(ui, 'menu', side_effect=['a', 's']), patch.object(ui, 'prompt', return_value='/path with spaces'):
            self.assertEqual(ui.edit_list('paths', []), ['/path with spaces'])
        with patch.object(ui, 'menu', side_effect=['a', 's']), \
             patch.object(ui, 'prompt', return_value='gh'), \
             patch.object(ui, 'edit_list', return_value=['pr view']):
            self.assertEqual(ui.edit_table('brokered', {}), {'gh': ['pr view']})
        with patch.object(ui, 'menu', side_effect=['a', 's']), \
             patch.object(ui, 'prompt', side_effect=['claude/research', 'work']):
            self.assertEqual(ui.edit_table('logins', {}), {'claude/research': 'work'})

    def test_prompt_accept_and_cancel(self):
        with patch.object(S['curses'], 'curs_set'):
            ui = self.ui(['\x15', 'n', 'e', 'w', '\n'])
            self.assertEqual(ui.prompt('edit', 'old'), 'new')
            self.assertIsNone(self.ui(['\x1b']).prompt('edit', 'old'))

    def test_terminal_restores_screen_after_failure(self):
        ui = self.ui()
        def fail():
            raise OSError('launch failed')
        with patch.object(S['curses'], 'def_prog_mode'), patch.object(S['curses'], 'endwin'), \
             patch.object(S['curses'], 'reset_prog_mode') as reset, \
             patch('builtins.input', return_value=''), patch('sys.stdout', new_callable=io.StringIO) as output:
            ui.terminal(fail)
        reset.assert_called_once()
        self.assertIn('launch failed', ui.message)


if __name__ == '__main__':
    unittest.main()
