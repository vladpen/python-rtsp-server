import asyncio
from datetime import datetime, timedelta
import time
from _config import Config
from log import Log


class Storage:
    def __init__(self, camera_hash):
        self.hash = camera_hash

    async def run(self) -> None:
        """ Start fragments saving
        """
        while True:
            try:
                await self._save_fragment()
            except Exception as e:
                Log.print(f'Storage: ERROR: can\'t save fragment "{self.hash}", trying again ({repr(e)})')
                await asyncio.sleep(5)

    async def _save_fragment(self):
        """ We'll use system (linux) commands for this job
        """
        filename = time.strftime('%H:%M')
        dirname = time.strftime('%Y-%m-%d')

        cfg = Config.cameras[self.hash]
        path = f'{Config.storage_path}/{cfg["path"]}/{dirname}'

        await self._mkdir(path)

        if 'storage_command' in cfg and cfg['storage_command']:
            cmd = cfg['storage_command']
        elif hasattr(Config, 'storage_command') and Config.storage_command:
            cmd = Config.storage_command
        else:
            raise RuntimeError('invalid "storage_command" in _config.py')

        cmd = cmd.replace('{url}', cfg['url']).replace('{filename}', f'{path}/{filename}')
        try:
            _done, pending = await asyncio.wait(
                [self._execute(cmd)],
                timeout=Config.storage_fragment_secs,
                return_when=asyncio.FIRST_COMPLETED)

            for t in pending:
                t.cancel()
        finally:
            await self._kill('fragment saved')

    async def _execute(self, cmd):
        """ Run given cmd in background
        """
        self.main_process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        Log.print(f'Storage: execute shell command:\n{cmd}')

        _stdout, stderr = await self.main_process.communicate()
        if stderr:
            Log.print(f"Storage: ERROR: can't execute command ({self.hash}):\n{cmd} ({stderr.decode()})")
            await asyncio.sleep(1)

    async def _kill(self, msg):
        """ Kill subprocess(es) and clean old storage files
        """
        # Main process may call subprocess(es), kill them all.
        # For example, we can list processes for openRTSP:
        # ps -x -o pid,ppid,pgid,sid,command | grep -w openRTSP
        cmd = f"pkill -TERM -P {int(self.main_process.pid)}"  # kill by parent ID
        p = await asyncio.create_subprocess_shell(cmd)
        await p.wait()
        self.main_process.kill()

        # Delete all subdirectories older than "storage_period_days"
        try:
            cfg = Config.cameras[self.hash]
            await self._delete_old_dir(f'{Config.storage_path}/{cfg["path"]}')
        except Exception as e:
            Log.print(f'Storage: cleanup ERROR "{self.hash}" ({repr(e)})')

        Log.print(f'Storage: process {self.main_process.pid} killed, "{self.hash}" folder cleaned ({msg})')

    async def _delete_old_dir(self, path):
        cmd = f'ls -d {path}/*/'
        p = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        stdout, _stderr = await p.communicate()
        if not stdout:
            return
        oldest_dirname = (datetime.now() - timedelta(days=Config.storage_period_days)).strftime('%Y-%m-%d')

        for row in stdout.decode().split('\n'):
            dir = row[:-1].split('/')
            # use comparison regarding a lexicographical order, not mtime
            if not row or not dir[-1] or dir[-1] >= oldest_dirname:
                continue
            cmd = f'rm -rf {path}/{dir[-1]}'
            proc = await asyncio.create_subprocess_shell(cmd)
            await proc.wait()

    async def _mkdir(self, folder):
        """ Create storage folder if not exists
        """
        cmd = f'mkdir -p {folder}'
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.wait()

    async def watchdog(self) -> None:
        """ Infinite loop for checking camera(s) availability
        """
        while True:
            await asyncio.sleep(Config.watchdog_interval)
            try:
                await self._watchdog()
            except Exception as e:
                Log.print(f'Storage: watchdog ERROR: can\'t restart storage "{self.hash}" ({repr(e)})')

    async def _watchdog(self):
        """ Extremely important piece.
            Cameras can turn off on power loss, or external commands can freeze.
        """
        cfg = Config.cameras[self.hash]
        dirname = time.strftime('%Y-%m-%d')
        path = f'{Config.storage_path}/{cfg["path"]}/{dirname}'

        # Get last modify time of most recent file
        cmd = f'cd {path} && stat -c %Y $(ls -Art | tail -n 1)'

        p = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        Log.print(f'Storage: watchdog: execute shell command:\n{cmd}')

        stdout, _stderr = await p.communicate()
        last_time = stdout.decode()
        if not last_time:
            return

        time_delta = int(time.time()) - int(last_time)

        # Check if saving is freezing
        if time_delta < Config.watchdog_interval:
            return

        await self._kill('watchdog')

        await asyncio.sleep(1)

        Log.print(f'Storage: watchdog: restart "{self.hash}"')
