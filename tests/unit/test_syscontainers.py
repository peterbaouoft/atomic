#pylint: skip-file

import os
import shutil
import tempfile
import unittest
import subprocess

from Atomic import util
from Atomic.syscontainers import SystemContainers


no_mock = True
try:
    from unittest.mock import ANY, patch, call
    no_mock = False
except ImportError:
    try:
        from mock import ANY, patch, call
        no_mock = False
    except ImportError:
        # Mock is already set to False
        pass

if no_mock:
    # If there is no mock, we need need to create a fake
    # patch decorator
    def fake_patch(a, new=''):
        def foo(func):
            def wrapper(*args, **kwargs):
                ret = func(*args, **kwargs)
                return ret
            return wrapper
        return foo

    patch = fake_patch

@unittest.skipIf(no_mock, "Mock not found")
class TestSystemContainers_do_checkout(unittest.TestCase):
    """
    Unit tests for refactored function from SystemContainers.do_checkout method.
    """
    def test_get_remote_location(self):
        """
        We create temp directories in tmp folder, then remove it after the test completes

        """
        # Create directories for 3 different cases '_get_remote_location' is checking
        try:
            os.makedirs('/tmp/test-remote/rootfs/usr')
            os.mkdir('/tmp/not-valid-test')
        # If the directories already exist, we do not error out here
        except OSError:
            pass

        try:
            # Here: we check for 3 different cases _get_remote_location verifies
            sc = SystemContainers()
            remote_path_one = sc._get_remote_location('/tmp/test-remote/')
            self.assertEqual(remote_path_one, os.path.realpath('/tmp/test-remote'))

            remote_path_two = sc._get_remote_location('/tmp/test-remote/rootfs/')
            self.assertEqual(remote_path_two, os.path.realpath('/tmp/test-remote'))

            self.assertRaises(ValueError, sc._get_remote_location, '/tmp/not-valid-test')
        finally:
            # We then remove the directories to keep the user's fs clean
            os.rmdir('/tmp/not-valid-test')
            shutil.rmtree('/tmp/test-remote')

@unittest.skipIf(no_mock, "Mock not found")
class TestSystemContainers_container_exec(unittest.TestCase):
    """
    Unit tests for the SystemContainres.container_exec method.
    """

    class Args():
        """
        Fake argument object for use in tests.
        """
        def __init__(self, atomic_config=None, backend=None, user=False, args=None, setvalues=None, display=False):
            self.atomic_config = atomic_config or util.get_atomic_config()
            self.backend = backend
            self.user = user
            self.args = args or []
            self.setvalues = setvalues
            self.display = display

    def test_container_exec_in_usermode(self):
        """
        A ValueError should be raised as usermode is not supported.
        """
        args = self.Args(backend='ostree')
        sc = SystemContainers()
        sc.set_args(args)
        self.assertRaises(ValueError, sc.container_exec, 'test', False, {})

    @patch('Atomic.syscontainers.SystemContainers._is_service_active')
    @patch('Atomic.util.is_user_mode')
    @patch('Atomic.backendutils.BackendUtils.get_backend_and_container_obj')
    def test_container_exec_not_running_no_checkout(self, _gb, _um, _sa):
        """
        A ValueError should be raised when the container is not running and there is no checkout.
        """
        _sa.return_value = False  # The service is not active
        _um.return_value = False  # user mode is False
        _gb.return_value = None  # The checkout is None

        args = self.Args(backend='ostree')
        sc = SystemContainers()
        sc.set_args(args)
        self.assertRaises(ValueError, sc.container_exec, 'test', False, {})

    @patch('Atomic.syscontainers.SystemContainers._is_service_active')
    @patch('Atomic.util.is_user_mode')
    @patch('Atomic.syscontainers.SystemContainers._canonicalize_location')
    def test_container_exec_not_running_with_detach(self, _cl, _um, _sa):
        """
        A ValueError should be raised when the container is not running and detach is requested.
        """
        _sa.return_value = False  # The service is not active
        _um.return_value = False  # user mode is False
        _cl.return_value = "/var/lib/containers/atomic/test.0"  # Fake a checkout

        args = self.Args(backend='ostree')
        sc = SystemContainers()
        sc.set_args(args)
        self.assertRaises(ValueError, sc.container_exec, 'test', True, {})  # Run with detach as True

    @patch('Atomic.syscontainers.SystemContainers._is_service_active')
    @patch('Atomic.util.check_call')
    @patch('Atomic.util.is_user_mode')
    def test_container_exec_with_container_running(self, _um, _cc, _sa):
        """
        Expect the container exec command to be used when container is running.
        """
        cmd_call = [util.RUNC_PATH, 'exec', 'test']
        if os.isatty(0):  # If we are a tty then we need to pop --tty in there
            cmd_call.insert(2, '--tty')
        expected_call = call(cmd_call, stderr=ANY, stdin=ANY, stdout=ANY)

        _sa.return_value = True  # The service is active
        _um.return_value = False  # user mode is False
        args = self.Args(backend='ostree', user=False)
        sc = SystemContainers()
        sc.set_args(args)
        sc.container_exec('test', False, {})

        self.assertEqual(_cc.call_args, expected_call)

    @patch('Atomic.syscontainers.SystemContainers._is_service_active')
    @patch('subprocess.Popen')
    @patch('Atomic.util.is_user_mode')
    @patch('Atomic.syscontainers.SystemContainers._canonicalize_location')
    def test_container_exec_without_container_running(self, _ce, _um, _cc, _sa):
        """
        Expect the container to be started if it's not already running.
        """
        expected_args = [util.RUNC_PATH, 'run', 'test']

        _sa.return_value = False  # The service is not active
        _um.return_value = False  # user mode is False
        tmpd = tempfile.mkdtemp()
        try:
            _ce.return_value = tmpd  # Use a temporary directory for testing
            args = self.Args(backend='ostree', user=False)
            sc = SystemContainers()
            sc.set_args(args)

            shutil.copy('./tests/test-images/system-container-files-hostfs/config.json.template', os.path.join(tmpd, 'config.json'))

            sc.container_exec('test', False, {})
            self.assertEqual(_cc.call_args[0][0], expected_args)
        finally:
            shutil.rmtree(tmpd)


class TestSystemContainers_get_skopeo_args(unittest.TestCase):
    """
    Unit tests for the SystemContainres._get_skopeo_args method.
    """

    def setUp(self):
        self.sc = SystemContainers()

    def test_get_skopeo_args(self):
        """
        Verify _get_skopeo_args return proper data when passing in different image uris.
        """
        for test_image, expected_insecure, expected_image in (
                # Explicitly insecure
                ('http:docker.io/busybox:latest', True, 'docker.io/busybox:latest'),
                # Implicitly secure
                ('docker.io/busybox:latest', False, 'docker.io/busybox:latest'),
                ('https:docker.io/busybox:latest', False, 'docker.io/busybox:latest'),
                ('oci:docker.io/busybox:latest', False, 'docker.io/busybox:latest')):
            # Make the call
            insecure, image = self.sc._get_skopeo_args(test_image)
            # Verify the results
            self.assertEqual(expected_insecure, insecure)
            self.assertEqual(expected_image, image)

    # def test_get_skopeo_args_with_full_resolution(self):


if __name__ == '__main__':
    unittest.main()
