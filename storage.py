import asyncio
import time
from _config import Config
# from shared import Shared
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
            except Exception:
                Log.print(f'Storage: error: can\'t save fragment "{self.hash}", trying again')
                await asyncio.sleep(5)

    async def _save_fragment(self):
        """ We'll use system (linux) commands for this job
        """
        filename = time.strftime('%H:%M')
        dirname = time.strftime('%Y-%m-%d')

        cfg = Config.cameras[self.hash]
        path = f'{Config.storage_path}/{cfg["path"]}/{dirname}'

        await self._mkdir(path)

        if cfg['storage_save_from_camera']:
            url = cfg['url']
        else:
            url = f'rtsp://localhost:{Config.rtsp_port}/{self.hash}'

        cmd = cfg['storage_command'].format(url, f'{path}/{filename}')

        try:
            await asyncio.wait_for(
                self._execute(cmd),
                timeout=Config.storage_fragment_secs)
        except asyncio.TimeoutError:
            pass

        await self._kill()

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
            Log.print(f"Storage: error: can't execute command ({self.hash}):\n{cmd}")

    async def _kill(self):
        """ Kill subprocess(es) and clean old storage files
        """
        # Main process may call subprocess(es), kill them all.
        # For example, we can list processes for openRTSP:
        # ps -x -o pid,ppid,pgid,sid,command | grep -w openRTSP
        cmd = f"pkill -TERM -P {int(self.main_process.pid)}"  # kill by parent ID
        p = await asyncio.create_subprocess_shell(cmd)
        await p.wait()
        self.main_process.kill()

        # Delete all files and subdirectories older than "storage_period_days"
        cmd = f'find {Config.storage_path} -type d -mtime +{Config.storage_period_days} -delete; ' \
            f'find {Config.storage_path} -type f -mtime +{Config.storage_period_days} -delete'
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.wait()

        Log.print(f'Storage: kill process {self.main_process.pid}, clean storage folder')

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
            except Exception:
                Log.print(f'Storage: watchdog error: can\'t restart storage "{self.hash}"')

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

        time_delta = int(time.time()) - int(stdout.decode())

        # Check if saving is freezing
        if time_delta < Config.watchdog_interval:
            return

        await self._kill()

        await asyncio.sleep(1)

        Log.print(f'Storage: watchdog: restart "{self.hash}" storage')
