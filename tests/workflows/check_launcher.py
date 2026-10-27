#!/usr/bin/env python3
"""Check launcher invalidation, incremental builds, dispatch and failure handling."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('launcher', ROOT / 'tools/run.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.build = self.root / 'build/host-release'
        self.build.mkdir(parents=True)
        (self.root / 'cmake').mkdir()
        (self.root / 'CMakeLists.txt').write_text('project(test)')
        (self.root / 'CMakePresets.json').write_text('{}')
        self.commands = []
        for name, value in [('ROOT', self.root), ('BUILD', self.build),
                            ('STAMP', self.build / '.routeproof-launcher.json')]:
            patch = mock.patch.object(launcher, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.dict(os.environ, {'PATH': '/test'}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        for target, value in [('shutil.which', sys.executable), ('subprocess.run', self.execute)]:
            obj, attr = (launcher.shutil, 'which') if target.endswith('which') else (launcher.subprocess, 'run')
            patch = mock.patch.object(obj, attr, return_value=value) if attr == 'which' else mock.patch.object(obj, attr, side_effect=value)
            patch.start()
            self.addCleanup(patch.stop)

    def execute(self, command, **kwargs):
        self.commands.append(command)
        self.assertEqual(kwargs['cwd'], self.root)
        self.assertIs(kwargs['stdout'], sys.stderr)
        self.assertTrue(kwargs['check'])
        if '--build' not in command:
            (self.build / 'CMakeCache.txt').write_text(
                f'CMAKE_HOME_DIRECTORY:INTERNAL={self.root}\nCMAKE_GENERATOR:INTERNAL=Ninja\n'
                f'CMAKE_CXX_COMPILER:FILEPATH={sys.executable}\n')
            (self.build / 'build.ninja').touch()
        else:
            # Represent the incremental build observing source edits, even when
            # no configure is needed. Real compilation is checked separately.
            (self.build / 'routeproof').write_text((self.root / 'source.cpp').read_text()
                                                   if (self.root / 'source.cpp').exists() else 'v1')

    def build_once(self):
        self.commands.clear()
        launcher.build_release()
        return self.commands.copy()

    def test_bootstrap_repeat_and_source_edit_always_build(self):
        self.assertEqual(len(self.build_once()), 2)
        self.assertEqual(len(self.build_once()), 1)
        (self.root / 'source.cpp').write_text('v2')
        self.assertEqual(len(self.build_once()), 1)
        self.assertEqual((self.build / 'routeproof').read_text(), 'v2')
        launcher.build_release(all_targets=True)
        self.assertNotIn('--target', self.commands[-1])

    def test_configuration_inputs_environment_cache_and_missing_build(self):
        self.build_once()
        mutations = [lambda: (self.root / 'CMakePresets.json').write_text('{"version":6}'),
                     lambda: (self.root / 'CMakeUserPresets.json').write_text('{}'),
                     lambda: (self.root / 'cmake/new.cmake').write_text('# changed'),
                     lambda: os.environ.update(CXX=sys.executable),
                     lambda: os.environ.update(CMAKE_TOOLCHAIN_FILE='/test/toolchain.cmake'),
                     lambda: os.environ.pop('CXX'),
                     lambda: os.environ.update(CXXFLAGS='-O2'),
                     lambda: (self.build / 'build.ninja').unlink(),
                     lambda: (self.build / 'CMakeCache.txt').write_text('CMAKE_HOME_DIRECTORY:INTERNAL=/other\n')]
        for index, mutate in enumerate(mutations):
            mutate()
            self.assertEqual(len(self.build_once()), 2)
            if index in (3, 4, 5, 8):
                self.assertIn('--fresh', self.commands[0])
            if index == 6:
                self.assertNotIn('--fresh', self.commands[0])
                self.assertEqual(self.commands[0][-2:], ['-U', 'CMAKE_CXX_FLAGS'])
        os.environ['PRIVATE_TEST_TOKEN'] = 'do-not-save-secret'
        self.build_once()
        self.assertNotIn('do-not-save-secret', launcher.STAMP.read_text())
        for key in ('PWD', 'OLDPWD', 'SHLVL', '_'):
            os.environ[key] = 'shell-bookkeeping'
        self.assertEqual(len(self.build_once()), 1)

    def test_toolchain_file_and_compiler_replacement_invalidate(self):
        self.build_once()
        toolchain = self.root / 'toolchain.cmake'
        toolchain.write_text('# v1')
        with (self.build / 'CMakeCache.txt').open('a') as cache:
            cache.write(f'CMAKE_TOOLCHAIN_FILE:FILEPATH={toolchain}\n')
        stamp = launcher.configuration(launcher.cache_entries())
        launcher.STAMP.write_text(json.dumps(stamp))
        toolchain.write_text('# v2')
        self.assertEqual(len(self.build_once()), 2)
        compiler = self.root / 'compiler'
        compiler.write_text('compiler v1')
        with mock.patch.object(launcher.shutil, 'which', return_value=str(compiler)):
            self.build_once()
            self.assertEqual(len(self.build_once()), 1)
            compiler.write_text('replacement compiler v2')
            self.assertEqual(len(self.build_once()), 2)

    def test_included_presets_fall_back_and_failed_build_is_not_stamped(self):
        (self.root / 'CMakeUserPresets.json').write_text('{"include":["external.json"]}')
        self.assertEqual(len(self.build_once()), 2)
        self.assertEqual(len(self.build_once()), 2)
        (self.root / 'CMakeUserPresets.json').unlink()
        with mock.patch.object(launcher.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'cmake')):
            self.assertEqual(launcher.main(['--version']), 3)
        self.assertFalse(launcher.STAMP.exists())

    def test_forward_arguments_and_exit_code(self):
        with mock.patch.object(launcher.os, 'execv', side_effect=SystemExit(1)) as dispatch:
            with self.assertRaises(SystemExit) as result:
                launcher.main(['simulate', 'scenario.json', '--out', 'fresh'])
            self.assertEqual(result.exception.code, 1)
        binary = str(self.build / 'routeproof')
        dispatch.assert_called_once_with(binary, [binary, 'simulate', 'scenario.json', '--out', 'fresh'])


class LauncherCMakeTests(unittest.TestCase):
    def test_flag_changes_preserve_manual_cache_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            build = root / 'build/host-release'
            (root / 'CMakeLists.txt').write_text(
                'cmake_minimum_required(VERSION 3.25.2)\n'
                'project(launcher_flags LANGUAGES CXX)\n'
                'include(CTest)\nadd_executable(routeproof main.cpp)\n')
            (root / 'main.cpp').write_text(
                '#ifndef FLAG_SELECTION\n#define FLAG_SELECTION 0\n#endif\n'
                'int main() { return CACHE_SELECTION + FLAG_SELECTION; }\n')
            (root / 'CMakePresets.json').write_text(json.dumps({
                'version': 6,
                'configurePresets': [{'name': 'host-release', 'generator': 'Ninja',
                                      'binaryDir': '${sourceDir}/build/host-release',
                                      'cacheVariables': {'CMAKE_BUILD_TYPE': 'Release'}}],
                'buildPresets': [{'name': 'host-release', 'configurePreset': 'host-release'}],
            }))
            environment = {key: value for key, value in os.environ.items()
                           if key not in launcher.INITIAL_ENVIRONMENT}
            release_flags = '-O1 -DCACHE_SELECTION=7'
            compiler = shutil.which('c++')
            self.assertIsNotNone(compiler, 'real launcher regression requires a C++ compiler')
            with mock.patch.multiple(launcher, ROOT=root, BUILD=build,
                                     STAMP=build / '.routeproof-launcher.json'), \
                    mock.patch.dict(os.environ, environment, clear=True):
                subprocess.run(['cmake', '--preset', 'host-release', '-DBUILD_TESTING=OFF',
                                '-DCMAKE_CXX_COMPILER=' + compiler,
                                '-DCMAKE_CXX_FLAGS_RELEASE=' + release_flags],
                               cwd=root, stdout=sys.stderr, check=True)
                launcher.build_release()
                selected_compiler = launcher.cache_entries()['CMAKE_CXX_COMPILER']

                def check_cache(expected_flags, expected_link_flags, exit_code):
                    cache = launcher.cache_entries()
                    self.assertEqual(cache['BUILD_TESTING'], 'OFF')
                    self.assertEqual(cache['CMAKE_CXX_COMPILER'], selected_compiler)
                    self.assertEqual(cache['CMAKE_CXX_FLAGS_RELEASE'], release_flags)
                    self.assertEqual(cache['CMAKE_CXX_FLAGS'], expected_flags)
                    for entry in launcher.FLAG_CACHE_ENTRIES['LDFLAGS']:
                        self.assertEqual(cache[entry], expected_link_flags)
                    self.assertEqual(subprocess.run([str(build / 'routeproof')]).returncode, exit_code)

                check_cache('', '', 7)
                os.environ['CXXFLAGS'] = '-DFLAG_SELECTION=10'
                launcher.build_release()
                check_cache('-DFLAG_SELECTION=10', '', 17)
                os.environ['CXXFLAGS'] = '-DFLAG_SELECTION=20'
                os.environ['LDFLAGS'] = '-L' + str(root)
                launcher.build_release()
                check_cache('-DFLAG_SELECTION=20', '-L' + str(root), 27)
                del os.environ['CXXFLAGS']
                del os.environ['LDFLAGS']
                launcher.build_release()
                check_cache('', '', 7)


if __name__ == '__main__':
    unittest.main()
