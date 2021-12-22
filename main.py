import asyncio
from _config import Config
from client import Client
from storage import Storage
from shared import Shared


async def main():
    # Start one listener for all clients
    tasks = [asyncio.create_task(Client.listen())]

    for camera_hash in Config.cameras.keys():
        # All tasks will communicate through this object
        Shared.data[camera_hash] = {'camera': None, 'clients': {}}

        # Start streams saving, if enabled
        if Config.storage_enable:
            s = Storage(camera_hash)
            tasks.append(asyncio.create_task(s.run()))
            tasks.append(asyncio.create_task(s.watchdog()))

    for t in tasks:
        await t


if __name__ == '__main__':
    asyncio.run(main())
